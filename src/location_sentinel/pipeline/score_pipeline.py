from __future__ import annotations

import logging
from datetime import date

from shapely.geometry import shape as shapely_shape

from ..compute.scoring import ScoreResult, compute_scores
from ..config import settings
from ..models.common import MetricName, QualityInfo
from ..storage.duckdb_store import store
from .features_pipeline import run_features

logger = logging.getLogger(__name__)


async def run_score(
    geom_geojson: dict,
    date_end: str,
    lookback_years: int = 5,
    location_key: str | None = None,
) -> tuple:
    """Run scoring pipeline: derive date range, compute features, score.

    Returns (location_key, score_result, features, quality, date_start, series).

    Fast path: if features already exist in DuckDB for the current
    PROCESSING_VERSION and date window, they are loaded directly and the full
    S2/SAR/TerraClimate pipeline is skipped entirely (no STAC search, no S3
    reads). This means a score-only recompute (SCORE_VERSION bump, no
    PROCESSING_VERSION change) completes in milliseconds.
    """
    d_end = date.fromisoformat(date_end)
    d_start = date(d_end.year - lookback_years, d_end.month, d_end.day)
    date_start = d_start.isoformat()

    # Look up climate zone once -- needed regardless of which path we take.
    climate_code: str | None = None
    try:
        centroid = shapely_shape(geom_geojson).centroid
        climate_code = store.lookup_climate(centroid.y, centroid.x)
    except Exception:
        logger.warning("Climate lookup failed for location_key=%s", location_key)

    # Fast path: features already computed for this version + date window.
    if location_key:
        cached = store.get_features(
            location_key, settings.PROCESSING_VERSION, date_start, date_end
        )
        if cached is not None:
            logger.info(
                "score fast-path: reusing stored features for %s (processing=%s)",
                location_key, settings.PROCESSING_VERSION,
            )
            features = cached["features"]
            quality = QualityInfo(**cached["quality"])
            series = store.get_timeseries(
                location_key, settings.PROCESSING_VERSION
            ) or {}
            result = compute_scores(features, climate_code=climate_code)
            return location_key, result, features, quality, date_start, series

    # Full pipeline: STAC search → COG reads → feature derivation.
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
        location_key=location_key,
    )

    result = compute_scores(features, climate_code=climate_code)
    return location_key, result, features, quality, date_start, series
