from __future__ import annotations

import asyncio
import logging
from functools import partial

from ..config import settings
from ..geometry.normalize import geojson_to_shapely
from ..stac.overture_client import query_buildings_sync
from ..storage.postgres_store import store

logger = logging.getLogger(__name__)

_NULL_RESULT = {
    "building_count": None,
    "building_fraction": None,
    "mean_building_height_m": None,
}


async def run_buildings_features(
    geom_geojson: dict,
    location_key: str,
) -> dict[str, float | None]:
    """Return building footprint features from Overture Maps GeoParquet.

    Caches results per (location_key, overture_release) independently of
    PROCESSING_VERSION so that bumping the processing version for S2/SAR/DEM
    changes does not trigger a repeat Overture S3 query.
    """
    release = settings.OVERTURE_RELEASE
    try:
        cached = store.get_buildings(location_key, release)
        if cached is not None:
            logger.info("Buildings cache hit for %s (release=%s)", location_key, release)
            return cached

        geom = geojson_to_shapely(geom_geojson)
        centroid = geom.centroid
        lat, lon = centroid.y, centroid.x

        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            partial(
                query_buildings_sync,
                lat, lon,
                settings.OVERTURE_BUCKET,
                release,
            ),
        )

        # Cache on success (including zero-building results); skip on error
        # (all values None means the query itself failed).
        if result.get("building_fraction") is not None:
            store.store_buildings(location_key, result, release)

        return result

    except Exception as exc:
        logger.warning("Buildings pipeline failed for %s: %s", location_key, exc)
        return _NULL_RESULT
