from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from ..config import settings
from .asset_keys import earth_search_asset_key

logger = logging.getLogger(__name__)

_W = settings.COG_WINDOW_SIZE  # 64

# Lazy-initialized module-level S3 store singleton
_s3_store: Any | None = None


def _get_store() -> Any:
    global _s3_store
    if _s3_store is None:
        from obstore.store import S3Store
        _s3_store = S3Store(
            bucket=settings.AWS_SENTINEL_BUCKET,
            region=settings.AWS_SENTINEL_REGION,
            skip_signature=True,
        )
    return _s3_store


def _parse_s3_key(href: str) -> str:
    """Extract S3 object key from Earth Search HTTPS href.

    Input:  "https://sentinel-cogs.s3.us-west-2.amazonaws.com/{key}"
    Output: "{key}"
    """
    marker = "sentinel-cogs.s3.us-west-2.amazonaws.com/"
    return href.split(marker, 1)[1]


def _center_to_window(center_xy: tuple[float, float], transform: Any, size: int) -> Any:
    """Return a pixel Window of `size x size` centered on the given CRS coordinate.

    Uses the inverse affine transform to convert the UTM center point to
    fractional pixel coordinates, then builds a window anchored at the
    nearest integer pixel such that the center falls inside the window.
    """
    from async_geotiff import Window
    inv = ~transform
    col, row = inv * center_xy
    col_off = int(round(col)) - size // 2
    row_off = int(round(row)) - size // 2
    return Window(
        col_off=max(0, col_off),
        row_off=max(0, row_off),
        width=size,
        height=size,
    )


async def _read_band_async(
    href: str,
    center_xy: tuple[float, float],
) -> tuple[np.ndarray, Any, Any]:
    """Open a COG via async-geotiff and read a native-resolution window centered on the point.

    For 10m bands: reads exactly 64x64 native pixels (640m x 640m footprint).
    For 20m bands: reads 32x32 native pixels (same 640m x 640m footprint),
    then expands to 64x64 by 2x pixel repeat (nearest-neighbor, no interpolation)
    so all band arrays share the same shape for index computation.
    """
    from async_geotiff import GeoTIFF
    key = _parse_s3_key(href)
    logger.info("COG async read key=%s", key[:120])
    geotiff = await GeoTIFF.open(key, store=_get_store())

    # Detect native resolution from transform (pixel width in CRS units = meters for UTM)
    native_res = abs(geotiff.transform.a)
    native_size = _W // 2 if native_res > 15 else _W  # 32 for 20m bands, 64 for 10m bands

    window = _center_to_window(center_xy, geotiff.transform, size=native_size)
    result = await geotiff.read(window=window)
    data = result.data
    if data.ndim == 3:
        data = data[0]
    data = data.astype(np.float32)

    # For 20m bands: 2x block repeat to reach 64x64 (same footprint, no interpolation)
    if native_size < _W:
        data = np.repeat(np.repeat(data, 2, axis=0), 2, axis=1)

    return data, geotiff.transform, geotiff.crs


@dataclass
class SceneData:
    """Bands and metadata for a single scene read."""
    bands: dict[str, np.ndarray] = field(default_factory=dict)
    transform: Any = None
    crs: Any = None
    shape_10m: tuple[int, int] = (0, 0)


async def read_scene_bands(
    item: Any,
    center_xy: tuple[float, float],
    band_keys: list[str] | None = None,
    max_concurrent: int = settings.MAX_CONCURRENT_COG_READS,
) -> SceneData:
    """Read required bands from an Earth Search STAC item using async COG window reads.

    Reads exactly 64x64 native pixels centered on `center_xy` for 10m bands.
    For 20m bands (SCL, B11, B12), reads 32x32 native pixels covering the same
    640m x 640m footprint and expands to 64x64 by 2x pixel repeat.

    Args:
        item: pystac.Item from Earth Search v1.
        center_xy: (x, y) center coordinate in the scene's native UTM CRS.
        band_keys: Internal band keys to read (e.g. ["B04", "B08", "SCL"]).
        max_concurrent: Maximum simultaneous S3 connections.
    """
    if band_keys is None:
        band_keys = ["B04", "B08", "SCL"]

    sem = asyncio.Semaphore(max_concurrent)

    async def _read(band_key: str) -> tuple[str, np.ndarray, Any, Any]:
        async with sem:
            asset_key = earth_search_asset_key(band_key)
            if asset_key not in item.assets:
                logger.warning("Asset key '%s' not found in item %s", asset_key, item.id)
                return band_key, None, None, None
            href = item.assets[asset_key].href
            data, transform, crs = await _read_band_async(href, center_xy)
            return band_key, data, transform, crs

    results = await asyncio.gather(*[_read(k) for k in band_keys])

    scene = SceneData()
    for band_key, data, transform, crs in results:
        if data is None:
            continue
        scene.bands[band_key] = data
        if scene.transform is None:
            scene.transform = transform
            scene.crs = crs

    scene.shape_10m = (_W, _W)
    return scene
