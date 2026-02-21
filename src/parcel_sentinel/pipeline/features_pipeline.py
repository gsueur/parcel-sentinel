from __future__ import annotations

import logging

from ..compute.canopy import compute_canopy_proxy_from_series
from ..compute.features import (
    compute_anomaly_frequency,
    compute_mean,
    compute_quality_score,
    compute_trend_slope,
    compute_wetness_persistence,
)
from ..config import settings
from ..geometry.normalize import geojson_to_shapely, geometry_hash
from ..models.common import MetricName, QualityInfo
from .timeseries import run_timeseries

logger = logging.getLogger(__name__)


async def run_features(
    geom_geojson: dict,
    date_start: str,
    date_end: str,
    metrics: list[MetricName],
    buffers_m: list[int],
) -> tuple[str, dict[str, float | None], QualityInfo]:
    """Run features pipeline: timeseries -> derived features.

    Returns (parcel_key, features_dict, quality).
    """
    # Ensure we request the underlying metrics needed for features
    ts_metrics = list(set(metrics) - {MetricName.canopy_proxy})
    if not ts_metrics:
        ts_metrics = [MetricName.ndvi]

    parcel_key, series, quality = await run_timeseries(
        geom_geojson=geom_geojson,
        date_start=date_start,
        date_end=date_end,
        metrics=ts_metrics,
    )

    features: dict[str, float | None] = {}

    # NDVI features
    ndvi_records = series.get("ndvi", [])
    if ndvi_records:
        features["ndvi_mean_5y"] = compute_mean(ndvi_records)
        features["ndvi_trend_slope_5y"] = compute_trend_slope(ndvi_records)
        features["ndvi_anomaly_freq_5y"] = compute_anomaly_frequency(ndvi_records)

    # NDWI features
    ndwi_records = series.get("ndwi", [])
    if ndwi_records:
        features["ndwi_wetness_persistence_5y"] = compute_wetness_persistence(ndwi_records)

    # Canopy proxy from NDVI series
    if MetricName.canopy_proxy in metrics and ndvi_records:
        geom = geojson_to_shapely(geom_geojson)
        latitude = geom.centroid.y

        # For MVP: compute canopy proxy from the parcel's own NDVI series.
        # Buffer-based reads from surrounding area would require additional COG reads.
        # We use the parcel NDVI as the proxy for the parcel itself,
        # and approximate buffer values with the same series (documented limitation).
        canopy_val = compute_canopy_proxy_from_series(ndvi_records, latitude)
        for buf in sorted(buffers_m):
            features[f"canopy_proxy_{buf}m"] = canopy_val

    # Quality score
    features["quality_score"] = compute_quality_score(
        quality.months_total,
        quality.months_observed,
        quality.mean_cloud_fraction,
    )

    return parcel_key, features, quality
