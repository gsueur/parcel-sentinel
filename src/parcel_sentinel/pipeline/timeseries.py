from __future__ import annotations

import asyncio
import logging
import time

import numpy as np
import shapely

from ..compute.aggregation import MonthlyRecord, Observation, aggregate_monthly
from ..compute.indices import compute_ndvi, compute_ndwi_gao, spatial_mean
from ..config import settings
from ..geometry.normalize import geojson_to_shapely, geometry_hash
from ..geometry.reproject import get_utm_crs, reproject_geometry
from ..geometry.validate import validate_geometry
from ..models.common import MetricName, MonthRecord, QualityInfo
from ..raster.masking import MaskStats, apply_scl_mask, mask_band
from ..raster.reader import SceneData, read_scene_bands
from ..stac.client import SceneRef, search_scenes

logger = logging.getLogger(__name__)


def _extract_epsg(item) -> int | None:
    """Extract EPSG code from STAC item properties.

    Handles both `proj:epsg` (older) and `proj:code` (newer, e.g. "EPSG:32618").
    """
    epsg = item.properties.get("proj:epsg")
    if epsg is not None:
        return int(epsg)

    code = item.properties.get("proj:code", "")
    if code.upper().startswith("EPSG:"):
        return int(code.split(":")[1])

    return None


def _get_bounds_in_scene_crs(geom: shapely.Geometry, scene_crs_epsg: int | None) -> tuple[float, float, float, float]:
    """Get geometry bounds in scene CRS. Falls back to WGS84 bounds if no CRS info."""
    if scene_crs_epsg:
        import pyproj
        wgs84 = pyproj.CRS.from_epsg(4326)
        scene_crs = pyproj.CRS.from_epsg(scene_crs_epsg)
        geom_proj = reproject_geometry(geom, wgs84, scene_crs)
        return geom_proj.bounds
    return geom.bounds


async def _process_scene(
    scene_ref: SceneRef,
    geom: shapely.Geometry,
    metrics: list[MetricName],
) -> dict[str, Observation]:
    """Process a single scene: read bands (async), mask, compute indices."""
    item = scene_ref.item

    band_keys = ["B04", "B08", "SCL"]
    if MetricName.ndwi in metrics and "swir16" in item.assets:
        band_keys.append("B11")

    epsg = _extract_epsg(item)
    bounds = _get_bounds_in_scene_crs(geom, epsg)

    scene_data = await read_scene_bands(item, bounds, band_keys=band_keys)

    if not scene_data.bands:
        return {}

    scl = scene_data.bands.get("SCL")
    if scl is not None:
        valid_mask, mask_stats = apply_scl_mask(scl)
    else:
        ref_band = next(iter(scene_data.bands.values()))
        valid_mask = np.ones(ref_band.shape, dtype=bool)
        mask_stats = MaskStats(
            valid_pixel_count=int(ref_band.size),
            total_pixel_count=int(ref_band.size),
            cloud_fraction=0.0,
        )

    if mask_stats.valid_fraction < settings.MIN_VALID_PIXEL_FRACTION:
        return {}

    results: dict[str, Observation] = {}

    if MetricName.ndvi in metrics:
        nir = scene_data.bands.get("B08")
        red = scene_data.bands.get("B04")
        if nir is not None and red is not None:
            nir_masked = mask_band(nir, valid_mask)
            red_masked = mask_band(red, valid_mask)
            ndvi = compute_ndvi(nir_masked, red_masked)
            results["ndvi"] = Observation(
                month_key=scene_ref.month_key,
                mean_value=spatial_mean(ndvi),
                valid_pixel_count=mask_stats.valid_pixel_count,
                cloud_fraction=mask_stats.cloud_fraction,
            )

    if MetricName.ndwi in metrics:
        nir = scene_data.bands.get("B08")
        swir = scene_data.bands.get("B11")
        if nir is not None and swir is not None:
            nir_masked = mask_band(nir, valid_mask)
            swir_masked = mask_band(swir, valid_mask)
            ndwi = compute_ndwi_gao(nir_masked, swir_masked)
            results["ndwi"] = Observation(
                month_key=scene_ref.month_key,
                mean_value=spatial_mean(ndwi),
                valid_pixel_count=mask_stats.valid_pixel_count,
                cloud_fraction=mask_stats.cloud_fraction,
            )

    return results


async def run_timeseries(
    geom_geojson: dict,
    date_start: str,
    date_end: str,
    metrics: list[MetricName],
    max_scenes_per_month: int = settings.MAX_SCENES_PER_MONTH,
) -> tuple[str, dict[str, list[MonthlyRecord]], QualityInfo]:
    """Core timeseries pipeline: STAC search -> async COG read -> mask -> index -> aggregate.

    Returns (parcel_key, series_by_metric, quality).
    """
    geom = geojson_to_shapely(geom_geojson)
    geom = validate_geometry(geom)
    parcel_key = geometry_hash(geom)

    # STAC search (synchronous pystac-client call; run in executor to avoid blocking)
    loop = asyncio.get_event_loop()
    t0 = time.monotonic()
    from functools import partial
    search_result = await loop.run_in_executor(
        None,
        partial(
            search_scenes,
            geom,
            date_start,
            date_end,
            max_scenes_per_month=max_scenes_per_month,
        ),
    )
    logger.info(
        "STAC search completed in %.1fs scenes=%d",
        time.monotonic() - t0, len(search_result.scenes),
    )

    if not search_result.scenes:
        raise ValueError(f"No scenes found for date range {date_start} to {date_end}")

    # Process scenes with bounded concurrency (semaphore limits concurrent S3 connections)
    sem = asyncio.Semaphore(settings.MAX_CONCURRENT_COG_READS)

    async def _process_one(scene_ref: SceneRef) -> dict[str, Observation]:
        async with sem:
            return await _process_scene(scene_ref, geom, metrics)

    t1 = time.monotonic()
    scene_results = await asyncio.gather(*[_process_one(sr) for sr in search_result.scenes])
    logger.info(
        "COG reads completed in %.1fs scenes=%d",
        time.monotonic() - t1, len(search_result.scenes),
    )

    # Collect observations by metric
    observations_by_metric: dict[str, list[Observation]] = {}
    for metric in metrics:
        metric_key = metric.value
        if metric_key == "canopy_proxy":
            continue
        observations_by_metric[metric_key] = []

    for scene_obs_dict in scene_results:
        for metric_key, obs in scene_obs_dict.items():
            if metric_key in observations_by_metric:
                observations_by_metric[metric_key].append(obs)

    # Aggregate monthly
    series: dict[str, list[MonthlyRecord]] = {}
    for metric_key, obs_list in observations_by_metric.items():
        series[metric_key] = aggregate_monthly(obs_list)

    # Quality info
    all_months: set[str] = set()
    observed_months: set[str] = set()
    cloud_fracs: list[float] = []
    for metric_records in series.values():
        for rec in metric_records:
            all_months.add(rec.month)
            if rec.mean is not None:
                observed_months.add(rec.month)
            cloud_fracs.append(rec.cloud_fraction)

    from datetime import date
    d_start = date.fromisoformat(date_start)
    d_end = date.fromisoformat(date_end)
    total_months = (d_end.year - d_start.year) * 12 + (d_end.month - d_start.month) + 1

    quality = QualityInfo(
        months_total=total_months,
        months_observed=len(observed_months),
        mean_cloud_fraction=round(sum(cloud_fracs) / len(cloud_fracs), 4) if cloud_fracs else 0.0,
        flags=[],
    )

    if quality.months_observed < total_months * 0.5:
        quality.flags.append("low_observation_coverage")

    return parcel_key, series, quality
