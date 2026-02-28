from __future__ import annotations

import asyncio
import logging

from ..compute.canopy import compute_canopy_proxy_from_series
from ..compute.urban import detect_urban
from ..compute.features import (
    compute_anomaly_frequency,
    compute_bare_soil_frequency,
    compute_mean,
    compute_moisture_stress_frequency,
    compute_quality_score,
    compute_snow_persistence,
    compute_trend_slope,
    compute_wetness_persistence,
    get_persistent_burn_months,
)
from ..config import settings
from ..geometry.normalize import geojson_to_shapely
from ..models.common import MetricName, QualityInfo
from .timeseries import run_timeseries
from .sar_pipeline import run_sar_features
from .terraclimate_pipeline import run_terraclimate_features
from ..compute.sar_features import compute_sar_flood_anomaly, compute_sar_water_frequency
from ..storage.duckdb_store import store

logger = logging.getLogger(__name__)


async def run_features(
    geom_geojson: dict,
    date_start: str,
    date_end: str,
    metrics: list[MetricName],
    location_key: str | None = None,
) -> tuple[str, dict[str, float | None], QualityInfo, dict[str, list[dict]]]:
    """Run features pipeline: timeseries -> derived features.

    Returns (location_key, features_dict, quality).
    """
    # Ensure we request the underlying metrics needed for features
    ts_metrics = list(set(metrics) - {MetricName.canopy_proxy})
    if not ts_metrics:
        ts_metrics = [MetricName.ndvi]

    # Look up climate zone before parallel tasks so growing season is correct
    # for both canopy proxy (S2 path) and tmax_summer_mean (TerraClimate path).
    geom_centroid = geojson_to_shapely(geom_geojson).centroid
    climate_code: str | None = store.lookup_climate(geom_centroid.y, geom_centroid.x)

    # Run S2 timeseries, SAR, and TerraClimate pipelines concurrently
    (location_key, series, quality), sar_features, tc_features = await asyncio.gather(
        run_timeseries(
            geom_geojson=geom_geojson,
            date_start=date_start,
            date_end=date_end,
            metrics=ts_metrics,
            location_key=location_key,
        ),
        run_sar_features(
            geom_geojson=geom_geojson,
            date_start=date_start,
            date_end=date_end,
        ),
        run_terraclimate_features(
            geom_geojson=geom_geojson,
            date_start=date_start,
            date_end=date_end,
            climate_code=climate_code,
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
        # Anomaly-based fire detection: fraction of months where NBR drops more than
        # NBR_ANOMALY_THRESHOLD below the seasonal climatology for that calendar month.
        # This correctly ignores persistent low NBR from dormant vegetation, harvested
        # cropland, and semi-arid grassland (all normal for the site) while flagging
        # genuine fire events, which produce an abrupt NBR departure from the site norm.
        # NBR_BURN_THRESHOLD (absolute) is kept separately for SAR suppression.
        features["nbr_burn_freq_5y"] = compute_anomaly_frequency(
            nbr_records,
            threshold=settings.NBR_ANOMALY_THRESHOLD,
            min_consecutive=settings.NBR_MIN_CONSECUTIVE,
        )

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
        # For MVP: compute canopy proxy from the location's own NDVI series.
        # Buffer-based reads from surrounding area would require additional COG reads.
        # We use the location NDVI as the proxy for the location itself,
        # and approximate buffer values with the same series (documented limitation).
        canopy_val = compute_canopy_proxy_from_series(ndvi_records, geom_centroid.y, climate_code)
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
    # _sar_scene_fracs: list of (month_key, water_frac, rel_orbit)
    # _sar_scene_arrays: list of (month_key, scene_id, vv_dn, water_frac, rel_orbit)
    sar_scene_fracs: list[tuple[str, float, int]] = sar_features.pop("_sar_scene_fracs", [])
    sar_scene_arrays: list[tuple[str, str, object, float, int]] = sar_features.pop("_sar_scene_arrays", [])

    if sar_scene_fracs:
        # -- Chronic water frequency (snow- and burn-suppressed, orbit-stratified) --
        # Exclude months where co-located S2 NDSI confirms actual snow cover.
        # Note: flooded fields also produce high NDSI (specular reflection), so
        # snow suppression is intentionally limited to locations where persistent
        # snow is physically plausible (high elevation / high latitude).
        # For flood-prone lowland sites the suppression may over-exclude; the
        # anomaly metric below is immune to this because it uses all scenes.
        snow_months: set[str] = {
            rec.month for rec in ndsi_records
            if rec.mean is not None and rec.mean > settings.NDSI_SNOW_THRESHOLD
        }
        # Exclude months where co-located S2 NBR confirms a persistent anomalous
        # burn scar. Uses anomaly-based detection (same as fire score): only months
        # where NBR drops more than NBR_ANOMALY_THRESHOLD below the site's own
        # seasonal climatology are candidates. This correctly ignores naturally
        # low NBR in Mediterranean dry seasons (Cape Town fynbos, California
        # chaparral in unburned years) -- the seasonal low is normal for that site
        # so it has zero anomaly. Genuine fire scars produce abrupt departures
        # well below the seasonal norm and still trigger suppression.
        burn_months: set[str] = get_persistent_burn_months(
            nbr_records,
            threshold=settings.NBR_ANOMALY_THRESHOLD,
            min_consecutive=settings.NBR_MIN_CONSECUTIVE,
        )
        excluded_months = snow_months | burn_months
        non_snow_non_burn = [
            (mk, f, orbit) for mk, f, orbit in sar_scene_fracs
            if mk not in excluded_months
        ]
        if snow_months:
            logger.info(
                "SAR snow suppression: excluded %d snow months",
                len(snow_months),
            )
        if burn_months:
            logger.info(
                "SAR burn suppression: excluded %d burn months",
                len(burn_months),
            )
            quality.flags.append("sar_burn_suppression")
        sar_features["sar_water_freq_5y"] = (
            compute_sar_water_frequency(non_snow_non_burn) if non_snow_non_burn else None
        )

        # -- Flood anomaly (burn-suppressed, no snow suppression) --
        # Compares recent water_frac to historical seasonal baseline for the same
        # calendar month. Detects sudden flood events even when they coincide with
        # months that NDSI falsely flags as snow (flooded floodplains).
        # Burn months are excluded: a post-fire anomaly is not a flood anomaly.
        flood_anomaly = compute_sar_flood_anomaly(
            [(mk, f, orbit) for mk, f, orbit in sar_scene_fracs if mk not in burn_months],
            date_end,
        )
        if flood_anomaly is not None:
            sar_features["sar_flood_anomaly"] = flood_anomaly

    features.update(sar_features)
    if sar_features.get("sar_water_freq_5y") is None:
        quality.flags.append("no_sar_data")

    # Persist SAR VV arrays for report visualization
    for month_key, scene_id, vv_dn, water_frac, rel_orbit in sar_scene_arrays:
        store.store_sar_scene(
            location_key, scene_id, month_key,
            settings.PROCESSING_VERSION, vv_dn, water_frac, rel_orbit,
        )

    # TerraClimate climate features (tmax, tmin, ppt, vpd, PDSI derivatives)
    if tc_features.get("no_terraclimate_data"):
        quality.flags.append("no_terraclimate_data")
    else:
        features.update({k: v for k, v in tc_features.items() if k != "no_terraclimate_data"})

    # Urban detection
    is_urban = detect_urban(features)
    features["is_urban"] = 1.0 if is_urban else 0.0
    if is_urban:
        quality.flags.append("urban_location")

    return location_key, features, quality, series
