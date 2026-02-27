from __future__ import annotations

import asyncio
import logging
import time
from functools import partial

import numpy as np
import pyproj
import shapely

from ..compute.sar_features import compute_sar_water_frequency, compute_water_fraction
from ..config import settings
from ..geometry.normalize import geojson_to_shapely
from ..geometry.reproject import get_utm_crs, reproject_geometry
from ..geometry.validate import validate_geometry
from ..stac.s1_client import SARSceneRef, search_sar_scenes

logger = logging.getLogger(__name__)

# GDAL environment for anonymous S3 access (Sentinel-1 public bucket)
_GDAL_ENV = {
    "AWS_NO_SIGN_REQUEST": "YES",
    "AWS_REGION": settings.SAR_AWS_REGION,
    # Avoid expensive directory listings on every open
    "GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR",
    "CPL_VSIL_CURL_ALLOWED_EXTENSIONS": ".tiff,.tif",
}


def _parse_s1_s3_key(href: str) -> str:
    """Extract S3 object key from a Sentinel-1 asset href.

    Handles:
      - https://sentinel-s1-l1c.s3.eu-central-1.amazonaws.com/{key}
      - https://sentinel-s1-l1c.s3.amazonaws.com/{key}
      - https://sentinel-s1-l1c.s3-eu-central-1.amazonaws.com/{key}
      - s3://sentinel-s1-l1c/{key}
    """
    if href.startswith("s3://"):
        return href.split("/", 3)[3]
    for marker in (
        "sentinel-s1-l1c.s3.eu-central-1.amazonaws.com/",
        "sentinel-s1-l1c.s3.amazonaws.com/",
        "sentinel-s1-l1c.s3-eu-central-1.amazonaws.com/",
    ):
        if marker in href:
            return href.split(marker, 1)[1]
    # Generic fallback: drop scheme + host
    parts = href.split("/", 3)
    return parts[3] if len(parts) > 3 else href


def _read_vv_dn_sync(
    href: str,
    geom_centroid: shapely.Point,
) -> np.ndarray | None:
    """Read a 64x64 window of VV uint16 DN from a Sentinel-1 GRD file.

    S1 GRD Level-1 files use GCP-based geolocation (no affine transform).
    To guarantee a consistent ground footprint across all orbital passes,
    rasterio.warp.reproject() is called with the file's native GCPs and an
    explicit UTM destination transform that covers exactly GROUND_EXTENT_M
    metres centred on the target point.

    This is more robust than WarpedVRT approaches because:
    - The output geographic extent is fixed in UTM regardless of orbit or
      native pixel spacing -- no pixel-coordinate arithmetic needed.
    - reproject() inverts the GCP polynomial per output pixel, which works
      reliably for a small target window embedded in a large GCP scene.
    - Full-scene WarpedVRT + window computation (previous approach) produced
      identical results to the original code because with native_res ≈ 10 m
      and ground_extent_m = 640 m, half_w ≈ 32 = size//2.
    - Explicit small WarpedVRT with target transform returns all zeros with
      GCP polynomial sources (GDAL initialization limitation).

    Runs synchronously -- call from an asyncio executor.
    """
    import rasterio
    from rasterio.crs import CRS as RioCRS
    from rasterio.transform import from_bounds
    from rasterio.warp import reproject as rio_reproject, Resampling

    key = _parse_s1_s3_key(href)
    vsis3_path = f"/vsis3/{settings.SAR_AWS_BUCKET}/{key}"

    # Derive UTM CRS and project centroid
    wgs84 = pyproj.CRS.from_epsg(4326)
    utm_crs = get_utm_crs(geom_centroid.x, geom_centroid.y)
    proj = reproject_geometry(geom_centroid, wgs84, utm_crs)
    cx, cy = proj.x, proj.y

    target_crs = RioCRS.from_epsg(utm_crs.to_epsg())
    size = settings.COG_WINDOW_SIZE
    # Fixed ground extent: 64 pixels × 10 m/px = 640 m on each side.
    half = size * 10.0 / 2.0  # 320 m

    # Destination: exactly (cx±320 m, cy±320 m) in UTM, 64×64 pixels.
    # from_bounds produces a north-up transform (negative y pixel size).
    dst_transform = from_bounds(
        left=cx - half, bottom=cy - half,
        right=cx + half, top=cy + half,
        width=size, height=size,
    )

    try:
        with rasterio.Env(**_GDAL_ENV):
            with rasterio.open(vsis3_path) as src:
                gcps, gcp_crs = src.gcps
                destination = np.zeros((size, size), dtype=np.float32)
                rio_reproject(
                    source=rasterio.band(src, 1),
                    destination=destination,
                    gcps=gcps,
                    src_crs=gcp_crs,
                    dst_crs=target_crs,
                    dst_transform=dst_transform,
                    resampling=Resampling.bilinear,
                )
                data = destination.astype(np.uint16)
                logger.info(
                    "SAR read OK key=%.80s cx=%.1f cy=%.1f "
                    "%dx%d min=%d max=%d mean=%.1f",
                    key, cx, cy, size, size,
                    int(data.min()), int(data.max()), float(data.mean()),
                )
                if data.max() == 0:
                    logger.warning(
                        "SAR read returned all zeros key=%.80s -- "
                        "GCP reproject may have missed the source window",
                        key,
                    )
                    return None
                return data
    except Exception as exc:
        logger.warning("SAR VV read failed key=%.80s err=%s", key, exc)
        return None


async def _process_sar_scene(
    scene_ref: SARSceneRef,
    geom: shapely.Geometry,
    loop: asyncio.AbstractEventLoop,
) -> tuple[float | None, np.ndarray | None]:
    """Read VV band for one S1 scene; return (water_frac, vv_dn) or (None, None)."""
    item = scene_ref.item
    vv_asset = item.assets.get("vv")
    if vv_asset is None:
        logger.warning("No VV asset in S1 item %s", item.id)
        return None, None

    centroid = geom.centroid
    vv_dn = await loop.run_in_executor(
        None,
        partial(_read_vv_dn_sync, vv_asset.href, centroid),
    )
    if vv_dn is None:
        return None, None

    return compute_water_fraction(vv_dn), vv_dn


async def run_sar_features(
    geom_geojson: dict,
    date_start: str,
    date_end: str,
) -> dict[str, float | None]:
    """Search S1 GRD scenes, read VV COGs, compute sar_water_freq_5y.

    Returns {"sar_water_freq_5y": value} where value is None when no SAR
    data was found or the pipeline encountered an unrecoverable error.
    """
    try:
        geom = geojson_to_shapely(geom_geojson)
        geom = validate_geometry(geom)

        loop = asyncio.get_event_loop()
        t0 = time.monotonic()
        search_result = await loop.run_in_executor(
            None,
            partial(search_sar_scenes, geom, date_start, date_end),
        )
        logger.info(
            "S1 STAC search %.1fs scenes=%d",
            time.monotonic() - t0, len(search_result.scenes),
        )

        if not search_result.scenes:
            logger.info("No S1 scenes found -- no_sar_data")
            return {"sar_water_freq_5y": None, "_sar_scene_fracs": []}

        sem = asyncio.Semaphore(settings.MAX_CONCURRENT_COG_READS)

        async def _process_one(sr: SARSceneRef) -> tuple[float | None, np.ndarray | None]:
            async with sem:
                return await _process_sar_scene(sr, geom, loop)

        t1 = time.monotonic()
        results = await asyncio.gather(*[_process_one(sr) for sr in search_result.scenes])
        scene_fracs = [r[0] for r in results]
        scene_dns   = [r[1] for r in results]
        logger.info(
            "SAR reads %.1fs scenes=%d valid=%d",
            time.monotonic() - t1,
            len(search_result.scenes),
            sum(1 for f in scene_fracs if f is not None),
        )

        # Pair each water fraction with month_key and rel_orbit for downstream use.
        # rel_orbit is used to stratify the frequency computation by orbital pass,
        # avoiding look-angle-dependent backscatter bias from mixing passes.
        scene_pairs: list[tuple[str, float, int]] = [
            (sr.month_key, frac, sr.rel_orbit)
            for sr, frac in zip(search_result.scenes, scene_fracs)
            if frac is not None
        ]
        if not scene_pairs:
            return {"sar_water_freq_5y": None, "_sar_scene_fracs": [], "_sar_scene_arrays": []}

        # Tuples of (month_key, scene_id, vv_dn, water_frac, rel_orbit) for storage/viz
        sar_scene_arrays: list[tuple[str, str, np.ndarray, float, int]] = [
            (sr.month_key, sr.item.id, vv_dn, frac, sr.rel_orbit)
            for sr, frac, vv_dn in zip(search_result.scenes, scene_fracs, scene_dns)
            if frac is not None and vv_dn is not None
        ]

        valid_frac_orbit = [(f, orbit) for _, f, orbit in scene_pairs]
        water_freq = compute_sar_water_frequency(valid_frac_orbit)
        return {
            "sar_water_freq_5y": water_freq,
            "_sar_scene_fracs": scene_pairs,
            "_sar_scene_arrays": sar_scene_arrays,
        }

    except Exception as exc:
        logger.warning("SAR pipeline failed: %s -- returning no_sar_data", exc)
        return {"sar_water_freq_5y": None, "_sar_scene_fracs": []}
