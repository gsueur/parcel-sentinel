from __future__ import annotations

import logging
from datetime import date, timedelta

from ..compute.scoring import ScoreResult, compute_scores
from ..config import settings
from ..models.common import MetricName
from .features_pipeline import run_features

logger = logging.getLogger(__name__)


async def run_score(
    geom_geojson: dict,
    date_end: str,
    lookback_years: int = 5,
) -> tuple[str, ScoreResult]:
    """Run scoring pipeline: derive date range, compute features, score.

    Returns (location_key, score_result).
    """
    d_end = date.fromisoformat(date_end)
    d_start = date(d_end.year - lookback_years, d_end.month, d_end.day)
    date_start = d_start.isoformat()

    metrics = [
        MetricName.ndvi, MetricName.ndwi, MetricName.ndmi,
        MetricName.nbr, MetricName.ndsi, MetricName.bsi,
        MetricName.canopy_proxy,
    ]
    buffers_m = [50, 200]

    location_key, features, quality = await run_features(
        geom_geojson=geom_geojson,
        date_start=date_start,
        date_end=date_end,
        metrics=metrics,
        buffers_m=buffers_m,
    )

    result = compute_scores(features)
    return location_key, result
