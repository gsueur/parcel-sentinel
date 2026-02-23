from __future__ import annotations

import logging
from datetime import date

from shapely.geometry import shape as shapely_shape

from ..compute.scoring import ScoreResult, compute_scores
from ..config import settings
from ..models.common import MetricName
from ..storage.duckdb_store import store
from .features_pipeline import run_features

logger = logging.getLogger(__name__)


async def run_score(
    geom_geojson: dict,
    date_end: str,
    lookback_years: int = 5,
) -> tuple:
    """Run scoring pipeline: derive date range, compute features, score.

    Returns (location_key, score_result, features, quality, date_start, series).
    """
    d_end = date.fromisoformat(date_end)
    d_start = date(d_end.year - lookback_years, d_end.month, d_end.day)
    date_start = d_start.isoformat()

    metrics = [
        MetricName.ndvi, MetricName.ndwi, MetricName.ndmi,
        MetricName.nbr, MetricName.ndsi, MetricName.bsi,
        MetricName.canopy_proxy,
    ]

    location_key, features, quality, series = await run_features(
        geom_geojson=geom_geojson,
        date_start=date_start,
        date_end=date_end,
        metrics=metrics,
    )

    # Look up climate zone from centroid
    climate_code: str | None = None
    try:
        centroid = shapely_shape(geom_geojson).centroid
        climate_code = store.lookup_climate(centroid.y, centroid.x)
    except Exception:
        logger.warning("Climate lookup failed for location_key=%s", location_key)

    result = compute_scores(features, climate_code=climate_code)
    return location_key, result, features, quality, date_start, series
