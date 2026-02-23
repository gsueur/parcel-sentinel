from __future__ import annotations

import asyncio
import logging

from ..compute.canopy import compute_canopy_proxy_from_series
from ..compute.urban import detect_urban
from ..compute.features import (
    compute_anomaly_frequency,
    compute_bare_soil_frequency,
    compute_burn_frequency,
    compute_mean,
    compute_moisture_stress_frequency,
    compute_quality_score,
    compute_snow_persistence,
    compute_trend_slope,
    compute_wetness_persistence,
)
from ..config import settings
from ..geometry.normalize import geojson_to_shapely
from ..models.common import MetricName, QualityInfo
from .timeseries import run_timeseries
from .sar_pipeline import run_sar_features
from ..compute.sar_features import compute_sar_water_frequency
from ..storage.duckdb_store import store

logger = logging.getLogger(__name__)


async def run_features(
    geom_geojson: dict,
    date_start: str,
    date_end: str,
    metrics: list[MetricName],
) -> tuple[str, dict[str, float | None], QualityInfo, dict[str, list[dict]]]:
    """Run features pipeline: timeseries -> derived features.

    Returns (location_key, features_dict, quality).
    """
    # Ensure we request the underlying metrics needed for features
    ts_metrics = list(set(metrics) - {MetricName.canopy_proxy})
    if not ts_metrics:
        ts_metrics = [MetricName.ndvi]

    # Run S2 timeseries and SAR pipelines concurrently to keep wall-clock time flat
    (location_key, series, quality), sar_features = await asyncio.gather(
        run_timeseries(
            geom_geojson=geom_geojson,
            date_start=date_start,
            date_end=date_end,
            metrics=ts_metrics,
        ),
        run_sar_features(
            geom_geojson=geom_geojson,
            date_start=date_start,
            date_end=date_end,
        ),
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

    # NDMI features -- vegetation moisture stress
    ndmi_records = series.get("ndmi", [])
    if ndmi_records:
        features["ndmi_mean_5y"] = compute_mean(ndmi_records)
        features["ndmi_moisture_stress_freq_5y"] = compute_moisture_stress_frequency(ndmi_records)

    # NBR features -- fire / burn history
    nbr_records = series.get("nbr", [])
    if nbr_records:
        features["nbr_mean_5y"] = compute_mean(nbr_records)
        features["nbr_burn_freq_5y"] = compute_burn_frequency(nbr_records)

    # NDSI features -- snow cover persistence
    ndsi_records = series.get("ndsi", [])
    if ndsi_records:
        features["ndsi_snow_persistence_5y"] = compute_snow_persistence(ndsi_records)

    # BSI features -- bare soil exposure
    bsi_records = series.get("bsi", [])
    if bsi_records:
        features["bsi_mean_5y"] = compute_mean(bsi_records)
        features["bsi_bare_soil_freq_5y"] = compute_bare_soil_frequency(bsi_records)

    # Canopy proxy from NDVI series
    if MetricName.canopy_proxy in metrics and ndvi_records:
        geom = geojson_to_shapely(geom_geojson)
        latitude = geom.centroid.y

        # For MVP: compute canopy proxy from the location's own NDVI series.
        # Buffer-based reads from surrounding area would require additional COG reads.
        # We use the location NDVI as the proxy for the location itself,
        # and approximate buffer values with the same series (documented limitation).
        canopy_val = compute_canopy_proxy_from_series(ndvi_records, latitude)
        features["canopy_proxy"] = canopy_val

    # Quality score
    features["quality_score"] = compute_quality_score(
        quality.months_total,
        quality.months_observed,
        quality.mean_cloud_fraction,
    )

    # SAR features (Sentinel-1 flood detection, cloud-independent)
    # Apply snow-month suppression: S1 VV specular reflection from smooth snow/ice
    # is indistinguishable from open water at the DN threshold level. Exclude SAR
    # scenes from months where co-located S2 NDSI confirms snow cover (NDSI > 0.4).
    sar_scene_fracs: list[tuple[str, float]] = sar_features.pop("_sar_scene_fracs", [])
    sar_scene_arrays: list[tuple[str, str, object, float]] = sar_features.pop("_sar_scene_arrays", [])
    if sar_scene_fracs:
        snow_months: set[str] = {
            rec.month for rec in ndsi_records
            if rec.mean is not None and rec.mean > settings.NDSI_SNOW_THRESHOLD
        }
        if snow_months:
            non_snow_fracs = [f for mk, f in sar_scene_fracs if mk not in snow_months]
            logger.info(
                "SAR snow suppression: kept %d/%d scenes, excluded %d snow months",
                len(non_snow_fracs), len(sar_scene_fracs), len(snow_months),
            )
            sar_features["sar_water_freq_5y"] = (
                compute_sar_water_frequency(non_snow_fracs) if non_snow_fracs else None
            )

    features.update(sar_features)
    if sar_features.get("sar_water_freq_5y") is None:
        quality.flags.append("no_sar_data")

    # Persist SAR VV arrays for report visualization
    for month_key, scene_id, vv_dn, water_frac in sar_scene_arrays:
        store.store_sar_scene(
            location_key, scene_id, month_key,
            settings.PROCESSING_VERSION, vv_dn, water_frac,
        )

    # Urban detection
    is_urban = detect_urban(features)
    features["is_urban"] = 1.0 if is_urban else 0.0
    if is_urban:
        quality.flags.append("urban_location")

    return location_key, features, quality, series
