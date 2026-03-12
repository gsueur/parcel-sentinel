from __future__ import annotations

import asyncio
import logging

import numpy as np

from ..compute.canopy import compute_canopy_proxy_from_series
from ..compute.urban import detect_urban
from ..compute.features import (
    compute_anomaly_frequency,
    compute_bare_soil_frequency,
    compute_mean,
    compute_moisture_stress_frequency,
    compute_quality_score,
    compute_recent_anomaly_ratio,
    compute_snow_persistence,
    compute_trend_slope,
    compute_wetness_persistence,
    get_persistent_burn_months,
)
from ..config import settings
from ..geometry.normalize import geojson_to_shapely, geometry_hash
from ..models.common import MetricName, QualityInfo
from .timeseries import run_timeseries
from .sar_pipeline import run_sar_features
from .terraclimate_pipeline import run_terraclimate_features
from .dem_pipeline import run_dem_features
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

    # Pre-compute the location key so the DEM pipeline can check its cache
    # before the key is returned by run_timeseries.  geometry_hash is
    # deterministic, so run_timeseries will produce the same key.
    geom_shape = geojson_to_shapely(geom_geojson)
    if location_key is None:
        location_key = geometry_hash(geom_shape)

    geom_centroid = geom_shape.centroid
    climate_code: str | None = store.lookup_climate(geom_centroid.y, geom_centroid.x)

    # Run S2 timeseries, SAR, TerraClimate, and DEM pipelines concurrently
    (location_key, series, quality), sar_features, tc_features, dem_features = await asyncio.gather(
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
        run_dem_features(
            geom_geojson=geom_geojson,
            location_key=location_key,
        ),
    )

    features: dict[str, float | None] = {}

    # NDVI features
    ndvi_records = series.get("ndvi", [])
    if ndvi_records:
        features["ndvi_mean_5y"] = compute_mean(ndvi_records)
        features["ndvi_trend_slope_5y"] = compute_trend_slope(ndvi_records)
        features["ndvi_anomaly_freq_5y"] = compute_anomaly_frequency(ndvi_records)
        features["ndvi_momentum_ratio_1y"] = compute_recent_anomaly_ratio(
            ndvi_records, date_end, threshold=settings.NDVI_ANOMALY_THRESHOLD, direction="below"
        )

    # NDWI features
    ndwi_records = series.get("ndwi", [])
    if ndwi_records:
        features["ndwi_wetness_persistence_5y"] = compute_wetness_persistence(ndwi_records)
        features["ndwi_trend_slope_5y"] = compute_trend_slope(ndwi_records)

    # NDMI features -- vegetation moisture stress
    ndmi_records = series.get("ndmi", [])
    if ndmi_records:
        features["ndmi_mean_5y"] = compute_mean(ndmi_records)
        features["ndmi_moisture_stress_freq_5y"] = compute_moisture_stress_frequency(ndmi_records)
        features["ndmi_trend_slope_5y"] = compute_trend_slope(ndmi_records)
        features["ndmi_momentum_ratio_1y"] = compute_recent_anomaly_ratio(
            ndmi_records, date_end, threshold=settings.NDVI_ANOMALY_THRESHOLD, direction="below"
        )

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

    # DEM slope mask: exclude steep-terrain pixels from SAR water fraction.
    # SAR backscatter on slopes produces low-DN returns that mimic open water
    # (geometric artefact -- look-angle dependent, not a real water signal).
    # The elevation_array is guaranteed to be cached by run_dem_features above.
    _flat_mask: np.ndarray | None = None
    _elev_bytes = store.get_elevation_array(location_key)
    if _elev_bytes is not None:
        _sz = settings.COG_WINDOW_SIZE
        _elev_arr = np.frombuffer(bytes(_elev_bytes), dtype=np.float32).reshape(_sz, _sz)
        _px = settings.S2_PIXEL_SIZE_M
        _fill = float(np.nanmean(_elev_arr)) if not np.all(np.isnan(_elev_arr)) else 0.0
        _grad_row, _grad_col = np.gradient(np.nan_to_num(_elev_arr, nan=_fill))
        _slope_deg = np.degrees(np.arctan(np.sqrt((_grad_col / _px) ** 2 + (_grad_row / _px) ** 2)))
        _flat_mask = _slope_deg < settings.DEM_FLAT_SLOPE_THRESHOLD
        logger.info(
            "DEM flat mask: %.1f%% of window is flat (slope < %.0f°)",
            100.0 * _flat_mask.mean(),
            settings.DEM_FLAT_SLOPE_THRESHOLD,
        )

    # Recompute per-scene water fractions restricted to flat-terrain pixels.
    if _flat_mask is not None and sar_scene_arrays:
        from ..compute.sar_features import compute_water_fraction as _compute_wf
        _corrected = []
        for _mk, _sid, _vv_dn, _wf, _orbit in sar_scene_arrays:
            _cwf = _compute_wf(_vv_dn, _flat_mask)
            _corrected.append((_mk, _sid, _vv_dn, _cwf if _cwf is not None else _wf, _orbit))
        sar_scene_arrays = _corrected
        sar_scene_fracs = [(_mk, _wf, _orbit) for _mk, _sid, _vv, _wf, _orbit in sar_scene_arrays]

    # Burn months derived from NBR: used for SAR suppression and the active_fire flag.
    # Computed unconditionally (NBR does not depend on SAR data being available).
    burn_months: set[str] = get_persistent_burn_months(
        nbr_records,
        threshold=settings.NBR_ANOMALY_THRESHOLD,
        min_consecutive=settings.NBR_MIN_CONSECUTIVE,
    )

    if sar_scene_fracs:
        # -- Chronic water frequency (snow- and burn-suppressed, orbit-stratified) --
        snow_months: set[str] = {
            rec.month for rec in ndsi_records
            if rec.mean is not None and rec.mean > settings.NDSI_SNOW_THRESHOLD
        }
        excluded_months = snow_months | burn_months
        non_snow_non_burn = [
            (mk, f, orbit) for mk, f, orbit in sar_scene_fracs
            if mk not in excluded_months
        ]
        if snow_months:
            logger.info("SAR snow suppression: excluded %d snow months", len(snow_months))
        if burn_months:
            logger.info("SAR burn suppression: excluded %d burn months", len(burn_months))
            quality.flags.append("sar_burn_suppression")
        sar_features["sar_water_freq_5y"] = (
            compute_sar_water_frequency(non_snow_non_burn) if non_snow_non_burn else None
        )

        # -- Flood anomaly (no snow or burn suppression) --
        # Fire events increase SAR backscatter (char, rubble) -- they never mimic
        # the low-backscatter signature of water. Burn suppression here removes
        # historical months from the per-orbit baseline, which can drop it below
        # min_baseline_count and force the orbit-agnostic fallback. That fallback
        # mixes orbits with different incidence angles, creating a low mixed baseline
        # that makes a structurally dark orbit look anomalously wet.
        flood_anomaly = compute_sar_flood_anomaly(
            sar_scene_fracs,
            date_end,
        )
        if flood_anomaly is not None:
            sar_features["sar_flood_anomaly"] = flood_anomaly

    features.update(sar_features)
    if sar_features.get("sar_water_freq_5y") is None:
        quality.flags.append("no_sar_data")

    # Persist SAR VV arrays for report visualization.
    # Clear previous scenes for this version first so re-runs don't accumulate
    # duplicate rows when the STAC search returns different scene IDs.
    if sar_scene_arrays:
        store.delete_sar_scenes(location_key, settings.PROCESSING_VERSION)
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

    # Elevation features (Copernicus GLO-30)
    features.update({k: v for k, v in dem_features.items() if v is not None})
    if dem_features.get("elevation_m") is None:
        quality.flags.append("no_dem_data")

    # Urban detection
    is_urban = detect_urban(features)
    features["is_urban"] = 1.0 if is_urban else 0.0
    if is_urban:
        quality.flags.append("urban_location")

    # Tidal zone detection (NOAA CO-OPS proximity + elevation gate)
    # Elevation gate: tidal influence is physically impossible above a few metres MSL.
    # Sites like Pacific Palisades (142 m) are near a station but clearly not tidal.
    _elev_m = dem_features.get("elevation_m")
    _above_tidal_elev = _elev_m is not None and _elev_m > settings.TIDAL_ZONE_MAX_ELEV_M
    nearest_tidal = (
        None if _above_tidal_elev
        else store.get_nearest_tidal_station(
            geom_centroid.y, geom_centroid.x, settings.TIDAL_ZONE_RADIUS_KM,
        )
    )
    is_tidal_zone = nearest_tidal is not None
    features["is_tidal_zone"] = 1.0 if is_tidal_zone else 0.0
    features["nearest_tidal_station_km"] = nearest_tidal["distance_km"] if nearest_tidal else None
    if is_tidal_zone:
        quality.flags.append("tidal_zone")

    # Active episode flags (drives UI badges on report header and dashboard cards)
    _end_abs = int(date_end[:4]) * 12 + int(date_end[5:7])

    # active_flood: SAR acute anomaly > 10%, with optical or strong-anomaly corroboration.
    # Corroboration requires independent evidence to avoid SAR-slope artifacts (single orbit
    # hitting snow/rock at a look angle that mimics water):
    #   1. NDWI history shows surface water in >= 8% of months (optical evidence)
    #   2. Anomaly is very strong (> 35%) -- major event, override corroboration
    # SAR chronic (sar_water_freq) is intentionally NOT used: it can share the same
    # look-angle artifact as the acute signal, making it circular corroboration.
    _sar_anom = (features.get("sar_flood_anomaly") or 0.0)
    _flood_corroborated = (
        (features.get("ndwi_wetness_persistence_5y") or 0.0) > settings.SAR_ACTIVE_FLOOD_MIN_NDWI
        or _sar_anom > settings.SAR_ACTIVE_FLOOD_STRONG_ANOMALY
    )
    features["active_flood"] = 1.0 if (_sar_anom > 0.10 and _flood_corroborated) else 0.0

    # active_fire: any consecutive-confirmed burn month within 3 months of date_end
    features["active_fire"] = 1.0 if burn_months and any(
        _end_abs - (int(mk[:4]) * 12 + int(mk[5:7])) <= 3
        for mk in burn_months
    ) else 0.0

    # active_drought: any of the 3 most recent NDVI months below seasonal climatology,
    # with suppression guards:
    # 1. Snow months: NDSI > threshold depresses NDVI to near-zero, indistinguishable
    #    from drought stress spectrally.
    # 2. Tidal zone (NOAA CO-OPS proximity): site is persistently inundated by tides,
    #    NDVI governed by water/emergent vegetation dynamics, not moisture deficit.
    # 3. Persistently wet sites (marshes, wetlands) not in tidal database: SAR water
    #    frequency > 0.7 or NDWI persistence > 0.3 identifies these sites.
    _snow_months: set[str] = {
        r.month for r in ndsi_records
        if r.mean is not None and r.mean > settings.NDSI_SNOW_THRESHOLD
    }
    _site_is_wet = (
        is_tidal_zone
        or (features.get("sar_water_freq_5y") or 0.0) > 0.70
        or (features.get("ndwi_wetness_persistence_5y") or 0.0) > 0.30
    )
    _recent_drought = False
    if ndvi_records and not _site_is_wet:
        _valid_ndvi = [r for r in ndvi_records if r.mean is not None]
        _recent = [
            r for r in _valid_ndvi
            if _end_abs - (int(r.month[:4]) * 12 + int(r.month[5:7])) <= 3
            and r.month not in _snow_months
        ]
        if _recent:
            _by_cal: dict[int, list[float]] = {}
            for r in _valid_ndvi:
                _by_cal.setdefault(int(r.month[5:7]), []).append(r.mean)
            # Use median (not mean) so exceptional wet/dry years don't inflate the
            # seasonal baseline and cause false drought flags in normal years.
            def _median(vs: list[float]) -> float:
                s = sorted(vs)
                m = len(s) // 2
                return s[m] if len(s) % 2 else (s[m - 1] + s[m]) / 2
            _clim = {mo: _median(v) for mo, v in _by_cal.items()}
            # Require at least 2 of the recent months to be anomalously low.
            # A single month below threshold can be cloud contamination or normal
            # phenological variation; 2 consecutive anomalies indicate real stress.
            _drought_count = sum(
                1 for r in _recent
                if r.mean < _clim.get(int(r.month[5:7]), r.mean) - settings.NDVI_ANOMALY_THRESHOLD
            )
            _recent_drought = _drought_count >= 2
    features["active_drought"] = 1.0 if _recent_drought else 0.0

    return location_key, features, quality, series
