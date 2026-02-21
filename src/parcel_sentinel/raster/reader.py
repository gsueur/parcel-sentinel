from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from scipy.ndimage import zoom

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


def _bounds_to_window(bounds: tuple[float, float, float, float], transform: Any) -> Any:
    """Convert (minx, miny, maxx, maxy) bounds to a pixel Window using the affine transform."""
    from async_geotiff import Window
    inv = ~transform
    col_ul, row_ul = inv * (bounds[0], bounds[3])  # minx, maxy
    col_lr, row_lr = inv * (bounds[2], bounds[1])  # maxx, miny
    col_off = int(np.floor(min(col_ul, col_lr)))
    row_off = int(np.floor(min(row_ul, row_lr)))
    width = int(np.ceil(max(col_ul, col_lr))) - col_off
    height = int(np.ceil(max(row_ul, row_lr))) - row_off
    return Window(
        col_off=max(0, col_off),
        row_off=max(0, row_off),
        width=max(1, width),
        height=max(1, height),
    )


def _resample_to_w(arr: np.ndarray, order: int = 1) -> np.ndarray:
    """Resample any 2D or (1, H, W) array to (_W, _W)."""
    if arr.ndim == 3:
        arr = arr[0]
    if arr.shape == (_W, _W):
        return arr.astype(np.float32)
    factors = (_W / arr.shape[0], _W / arr.shape[1])
    return zoom(arr, factors, order=order).astype(np.float32)


async def _read_band_async(
    href: str,
    bounds: tuple[float, float, float, float],
    is_scl: bool = False,
) -> tuple[np.ndarray, Any, Any]:
    """Open a COG via async-geotiff, read the window, resample to (_W, _W)."""
    from async_geotiff import GeoTIFF
    key = _parse_s3_key(href)
    logger.info("COG async read key=%s", key[:120])
    geotiff = await GeoTIFF.open(key, store=_get_store())
    window = _bounds_to_window(bounds, geotiff.transform)
    result = await geotiff.read(window=window)
    order = 0 if is_scl else 1
    data = _resample_to_w(result.data, order=order)
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
    bounds: tuple[float, float, float, float],
    band_keys: list[str] | None = None,
    max_concurrent: int = settings.MAX_CONCURRENT_COG_READS,
) -> SceneData:
    """Read required bands from an Earth Search STAC item using async COG window reads.

    All bands are resampled to (_W, _W) = (64, 64) pixels regardless of native resolution.

    Args:
        item: pystac.Item from Earth Search v1.
        bounds: (minx, miny, maxx, maxy) in the scene's native CRS.
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
            data, transform, crs = await _read_band_async(
                href, bounds, is_scl=(band_key == "SCL")
            )
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
