from __future__ import annotations

import asyncio
import logging
from functools import partial

from ..geometry.normalize import geojson_to_shapely
from ..stac.dem_client import read_dem_sync
from ..storage.duckdb_store import store

logger = logging.getLogger(__name__)


async def run_dem_features(
    geom_geojson: dict,
    location_key: str,
) -> dict[str, float | None]:
    """Return elevation features for the location centroid.

    Checks the DuckDB elevation cache first; on a miss, reads from Copernicus
    GLO-30 via /vsis3/ in a thread executor and caches the result.

    Returns a dict with keys:
      elevation_m, elevation_range_m, slope_deg
    All values are None when the DEM tile is unavailable or the read fails.
    """
    try:
        cached = store.get_elevation(location_key)
        if cached is not None and store.get_elevation_array(location_key) is not None:
            logger.info("DEM cache hit for %s", location_key)
            return cached

        geom = geojson_to_shapely(geom_geojson)
        centroid = geom.centroid
        lat, lon = centroid.y, centroid.x

        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            partial(read_dem_sync, lat, lon),
        )

        if result is None:
            logger.warning("DEM unavailable for location %s (%.4f, %.4f)", location_key, lat, lon)
            return {
                "elevation_m": None, "elevation_min_m": None, "elevation_max_m": None,
                "elevation_range_m": None, "slope_deg": None,
                "aspect_deg": None, "tpi_m": None, "curvature": None, "heat_load_index": None,
            }

        store.store_elevation(location_key, result)
        return {k: v for k, v in result.items() if k != "elevation_array"}

    except Exception as exc:
        logger.warning("DEM pipeline failed for %s: %s", location_key, exc)
        return {
            "elevation_m": None, "elevation_min_m": None, "elevation_max_m": None,
            "elevation_range_m": None, "slope_deg": None,
            "aspect_deg": None, "tpi_m": None, "curvature": None, "heat_load_index": None,
        }
