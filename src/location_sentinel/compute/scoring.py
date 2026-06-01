from __future__ import annotations

from dataclasses import dataclass, field

from ..config import settings


def _sar_snow_artifact_risk(climate_code: str | None, elevation_m: float | None) -> float:
    """Estimate likelihood that SAR water signals are snow/ice artifacts (0.0-1.0).

    C-band SAR cannot distinguish liquid water from wet snow, frozen ground, or ice.
    High-elevation semi-arid and continental/boreal climates have extended snow seasons
    that inflate both sar_water_freq_5y and sar_flood_anomaly with non-water returns.

    base risk by Köppen major letter:
      E (polar/tundra)        → 1.00  always frozen
      D (continental/boreal)  → 0.80  long snowy winters
      B cold variants (BSk, BWk) → 0.65  cold semi-arid with snow
      B hot variants (BSh, BWh)  → 0.20  desert, no snow
      C (temperate)           → 0.20  mild winters, occasional snow at altitude
      A (tropical)            → 0.00  no snow

    elevation bonus: +0.40 max for every 4000m above 500m (linear).
    """
    major = (climate_code or "")[0] if climate_code else ""
    if major == "E":
        base = 1.00
    elif major == "D":
        base = 0.80
    elif major == "B":
        base = 0.65 if (climate_code or "").endswith("k") else 0.20
    elif major == "C":
        base = 0.20
    elif major == "A":
        base = 0.00
    else:
        base = 0.30
    elev_bonus = min(0.40, max(0.0, ((elevation_m or 0.0) - 500.0) / 4000.0))
    return min(1.0, base + elev_bonus)

# ---------------------------------------------------------------------------
# Climate-zone weight profiles for the composite score
# ---------------------------------------------------------------------------
# Keys: drought, wetness, fire, heat_inv (= 100 - heat_mitigation_score), flood,
#       heat_stress (TerraClimate-derived: tmax anomaly + trend + VPD).
# All six weights must sum to 1.0.
# Resolution order: "Cs" prefix first, then major letter, then "default".
_CLIMATE_WEIGHTS: dict[str, dict[str, float]] = {
    "A":       {"drought": 0.07, "wetness": 0.30, "fire": 0.08, "heat_inv": 0.20, "flood": 0.18, "heat_stress": 0.17},
    "B":       {"drought": 0.38, "wetness": 0.04, "fire": 0.16, "heat_inv": 0.20, "flood": 0.04, "heat_stress": 0.18},
    "Cs":      {"drought": 0.20, "wetness": 0.06, "fire": 0.28, "heat_inv": 0.14, "flood": 0.12, "heat_stress": 0.20},
    "C":       {"drought": 0.16, "wetness": 0.16, "fire": 0.12, "heat_inv": 0.20, "flood": 0.16, "heat_stress": 0.20},
    "D":       {"drought": 0.12, "wetness": 0.12, "fire": 0.24, "heat_inv": 0.20, "flood": 0.12, "heat_stress": 0.20},
    "E":       {"drought": 0.06, "wetness": 0.14, "fire": 0.04, "heat_inv": 0.44, "flood": 0.12, "heat_stress": 0.20},
    "default": {"drought": 0.22, "wetness": 0.16, "fire": 0.14, "heat_inv": 0.16, "flood": 0.12, "heat_stress": 0.20},
}

_CLIMATE_PROFILE_LABELS: dict[str, str] = {
    "A":       "Tropical",
    "B":       "Arid",
    "Cs":      "Mediterranean",
    "C":       "Temperate humid",
    "D":       "Continental / Boreal",
    "E":       "Polar / Alpine",
    "default": "Generic",
}


def _resolve_climate_key(code: str | None) -> str:
    if code:
        if code.startswith("Cs"):
            return "Cs"
        major = code[0]
        if major in _CLIMATE_WEIGHTS:
            return major
    return "default"


def climate_profile_label(code: str | None) -> str:
    """Return human-readable profile name for a Köppen code."""
    return _CLIMATE_PROFILE_LABELS[_resolve_climate_key(code)]


def climate_weights_for_code(code: str | None) -> dict[str, float]:
    """Return composite weight dict for a Köppen code (for display / reporting)."""
    return _CLIMATE_WEIGHTS[_resolve_climate_key(code)]


@dataclass
class ScoreResult:
    drought_score: int
    wetness_score: int
    fire_exposure_score: int
    heat_mitigation_score: int
    flood_risk_score: int
    heat_stress_score: int
    landslide_risk_score: int
    composite_score: int
    top_factors: list[dict]
    climate_profile: str = field(default="Generic")


def _clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> int:
    return int(max(lo, min(hi, round(value))))


def compute_scores(features: dict[str, float | None], climate_code: str | None = None) -> ScoreResult:
    """Compute risk sub-scores and composite from derived features.

    All scores are 0-100. Higher = more risk (except heat_mitigation where higher = more mitigation).
    Deterministic, versioned as risk-v1.21.0.

    Sub-scores:
    - drought_score:       NDVI anomaly frequency + trend + mean + NDMI moisture stress
    - wetness_score:       NDWI surface water persistence + trend slope
    - fire_exposure_score: NBR burn frequency over the lookback period
    - heat_mitigation:     Canopy proxy (higher = more shade = lower heat risk)
    - flood_risk_score:    SAR chronic inundation + acute anomaly + terrain flash/TPI
    - heat_stress_score:   TerraClimate tmax anomaly frequency + VPD trend
    - composite_score:     Climate-zone-weighted combination of the above
    """
    factors: list[dict] = []
    is_urban = (features.get("is_urban") or 0.0) > 0.5
    climate_key = _resolve_climate_key(climate_code)
    w = _CLIMATE_WEIGHTS[climate_key]
    profile = _CLIMATE_PROFILE_LABELS[climate_key]

    # --- Drought score (0-100) ---
    # Combines NDVI vegetation health, NDMI leaf moisture stress, and PDSI.
    anomaly_freq  = features.get("ndvi_anomaly_freq_5y")
    trend_slope   = features.get("ndvi_trend_slope_5y")
    ndvi_mean     = features.get("ndvi_mean_5y")
    ndmi_stress   = features.get("ndmi_moisture_stress_freq_5y")
    pdsi_drought  = features.get("pdsi_drought_freq_5y")

    drought_components: list[float] = []
    drought_weights: list[float] = []
    # PDSI / optical coherence veto: TerraClimate cell misaligned with micro-climate.
    # When PDSI reports high drought but NDVI shows no vegetation stress, the PDSI
    # signal is likely a grid artifact (orographic gradient, island topography).
    # Dampen both PDSI-derived components; optical (NDVI, NDMI) components are unaffected.
    pdsi_conflict_damp = (
        settings.PDSI_OPTICAL_CONFLICT_DAMP
        if (features.get("pdsi_optical_conflict") or 0.0) > 0.5
        else 1.0
    )

    if anomaly_freq is not None:
        drought_components.append(anomaly_freq * 100)
        drought_weights.append(0.20)
        if anomaly_freq > 0.15:
            factors.append({"name": "ndvi_anomaly_freq_5y", "direction": "positive", "weight": 0.20})

    if trend_slope is not None:
        # Negative slope = drying. Map [-0.05, 0.05] → [100, 0]
        slope_score = max(0, min(100, (0.05 - trend_slope) / 0.10 * 100))
        drought_components.append(slope_score)
        drought_weights.append(0.20)
        if trend_slope < -0.005:
            factors.append({"name": "ndvi_trend_slope_5y", "direction": "negative", "weight": 0.20})

    if ndvi_mean is not None:
        # Lower NDVI = more drought stress. Map [0, 0.8] → [100, 0]
        mean_score = max(0, min(100, (0.8 - ndvi_mean) / 0.8 * 100))
        drought_components.append(mean_score)
        drought_weights.append(0.15)

    if ndmi_stress is not None:
        # Fraction of months with vegetation moisture stress. Map [0, 1] → [0, 100]
        drought_components.append(ndmi_stress * 100)
        drought_weights.append(0.20)
        if ndmi_stress > 0.2:
            factors.append({"name": "ndmi_moisture_stress_freq_5y", "direction": "positive", "weight": 0.20})

    if pdsi_drought is not None:
        # Fraction of months with PDSI < -2 (moderate drought). Map [0, 1] → [0, 100]
        # Dampened by pdsi_conflict_damp when PDSI/optical coherence veto is active.
        drought_components.append(pdsi_drought * 100 * pdsi_conflict_damp)
        drought_weights.append(0.25)
        if pdsi_drought > 0.15 and pdsi_conflict_damp == 1.0:
            factors.append({"name": "pdsi_drought_freq_5y", "direction": "positive", "weight": 0.25})

    # Part C -- slope sub-components
    ndmi_trend = features.get("ndmi_trend_slope_5y")
    if ndmi_trend is not None:
        # Negative slope = worsening moisture stress. Map [abs(NDMI_TREND_STRESS_MAX), 0] → [100, 0]
        stress_slope_score = max(0.0, min(100.0, (-ndmi_trend / abs(settings.NDMI_TREND_STRESS_MAX)) * 100))
        drought_components.append(stress_slope_score)
        drought_weights.append(0.15)

    pdsi_trend = features.get("pdsi_trend_slope_5y")
    if pdsi_trend is not None:
        # Negative slope = worsening drought. Map [abs(PDSI_TREND_DROUGHT_MAX), 0] → [100, 0]
        # Dampened by pdsi_conflict_damp when PDSI/optical coherence veto is active.
        pdsi_slope_score = max(0.0, min(100.0, (-pdsi_trend / abs(settings.PDSI_TREND_DROUGHT_MAX)) * 100))
        drought_components.append(pdsi_slope_score * pdsi_conflict_damp)
        drought_weights.append(0.15)

    slope_deg = features.get("slope_deg")

    # HLI amplifier: south-facing slopes (NH) get higher solar load → drier soils,
    # higher heat stress. Computed independently of the drought branch so it also
    # amplifies heat_stress_score for locations without optical time series data.
    # Suppressed for urban locations: GLO-30 is a DSM, so rooftop edges corrupt
    # slope/aspect (and therefore HLI) in dense built-up areas.
    hli = features.get("heat_load_index")
    hli_amp = 1.0
    if hli is not None and hli > settings.TERRAIN_HLI_THRESHOLD and not is_urban:
        hli_amp = 1.0 + min(settings.TERRAIN_HLI_AMP_MAX, hli * settings.TERRAIN_HLI_FACTOR)

    if is_urban:
        drought_score = 0.0
    elif drought_components:
        total_w = sum(drought_weights)
        drought_score = sum(c * wt for c, wt in zip(drought_components, drought_weights)) / total_w
        # Terrain drought amplifier: steep slopes → thin soils → amplified drought stress
        if slope_deg is not None and slope_deg > settings.TERRAIN_DROUGHT_SLOPE_MIN:
            terrain_amp = 1.0 + min(
                settings.TERRAIN_DROUGHT_AMP_MAX,
                (slope_deg - settings.TERRAIN_DROUGHT_SLOPE_MIN) / 100.0,
            )
            drought_score = min(100.0, drought_score * terrain_amp)
        # HLI drought amplifier: more solar radiation → drier
        if hli_amp > 1.0:
            drought_score = min(100.0, drought_score * hli_amp)

        # Improving-slope mitigation: positive NDMI/PDSI trend → reduce drought score.
        # Suppressed when any worsening momentum ratio exceeds the priority threshold --
        # the recent trajectory then dominates over the long-term slope signal.
        drought_momentums = [
            features.get(k) for k in ("ndvi_momentum_ratio_1y", "ndmi_momentum_ratio_1y", "pdsi_momentum_ratio_1y")
        ]
        max_drought_momentum = max((m for m in drought_momentums if m is not None), default=0.0)
        momentum_dominates = max_drought_momentum >= settings.MOMENTUM_PRIORITY_THRESHOLD
        if not momentum_dominates:
            if ndmi_trend is not None and ndmi_trend > 0:
                mitig = min(0.15, (ndmi_trend / abs(settings.NDMI_TREND_STRESS_MAX)) * 0.20)
                drought_score = max(0.0, drought_score * (1.0 - mitig))
            if pdsi_trend is not None and pdsi_trend > 0:
                mitig = min(0.15, (pdsi_trend / abs(settings.PDSI_TREND_DROUGHT_MAX)) * 0.20)
                drought_score = max(0.0, drought_score * (1.0 - mitig))

        # Part B: momentum amplifiers / dampeners (worsening OR improving trajectory).
        # Progressive amplification: rate doubles above 2× to reflect accelerating risk.
        for momentum in drought_momentums:
            if momentum is None:
                continue
            if momentum > 1.0:
                excess = momentum - 1.0
                raw = excess * settings.MOMENTUM_AMP_SCALE + max(0.0, excess - 1.0) * settings.MOMENTUM_AMP_SCALE
                drought_score = min(100.0, drought_score * (1.0 + min(settings.MOMENTUM_AMP_MAX, raw)))
            elif 0.0 < momentum < 1.0:
                damp = 1.0 - min(settings.MOMENTUM_DAMP_MAX, (1.0 - momentum) * settings.MOMENTUM_AMP_SCALE)
                drought_score = max(0.0, drought_score * damp)

        # Part A: active episode boost
        if features.get("active_drought"):
            drought_score = min(100.0, drought_score * settings.ACTIVE_DROUGHT_BOOST)
    else:
        drought_score = 50.0

    # --- Wetness score (0-100) ---
    # Surface water persistence from McFeeters NDWI.
    ndwi_persistence = features.get("ndwi_wetness_persistence_5y")
    if ndwi_persistence is not None:
        wetness_score = ndwi_persistence * 100
        if ndwi_persistence > 0.3:
            factors.append({"name": "ndwi_wetness_persistence_5y", "direction": "positive", "weight": 0.25})
    else:
        wetness_score = 50.0

    # Part C: NDWI trend adjusts wetness bidirectionally
    ndwi_trend = features.get("ndwi_trend_slope_5y")
    if ndwi_trend is not None:
        if ndwi_trend > 0:
            trend_wet_score = min(100.0, (ndwi_trend / settings.NDWI_TREND_WET_MIN) * 100)
            wetness_score = min(100.0, wetness_score * 0.85 + trend_wet_score * 0.15)
        elif ndwi_trend < 0:
            # Drying trend: reduce wetness score (site becoming drier than its 5y average)
            mitig = min(0.15, (-ndwi_trend / settings.NDWI_TREND_WET_MIN) * 0.15)
            wetness_score = max(0.0, wetness_score * (1.0 - mitig))

    # --- Fire exposure score (0-100) ---
    # Fraction of months where NBR drops anomalously below the site's seasonal climatology
    # (NBR < climatology[calendar_month] - NBR_ANOMALY_THRESHOLD).
    # Anomaly-based: ignores persistent low NBR from dormant vegetation, harvested
    # cropland, and semi-arid grassland. Detects genuine fire events as abrupt departures.
    # 0 = no anomalous fire signal; 100 = repeated severe departures.
    nbr_burn_freq = features.get("nbr_burn_freq_5y")
    if is_urban:
        fire_exposure_score = 0.0
    elif nbr_burn_freq is not None:
        fire_exposure_score = min(100.0, nbr_burn_freq * 350)
        if nbr_burn_freq > 0.05:
            factors.append({"name": "nbr_burn_freq_5y", "direction": "positive", "weight": 0.20})
        # Part B: fire momentum amplifier (recent burn acceleration vs 5y baseline)
        nbr_momentum = features.get("nbr_momentum_ratio_1y")
        if nbr_momentum is not None and nbr_momentum > 1.0:
            excess = nbr_momentum - 1.0
            raw = excess * settings.MOMENTUM_AMP_SCALE + max(0.0, excess - 1.0) * settings.MOMENTUM_AMP_SCALE
            fire_exposure_score = min(100.0, fire_exposure_score * (1.0 + min(settings.MOMENTUM_AMP_MAX, raw)))
        # Part A: active episode boost (urban guard already handled above)
        if features.get("active_fire"):
            fire_exposure_score = min(100.0, fire_exposure_score * settings.ACTIVE_FIRE_BOOST)
    else:
        fire_exposure_score = 0.0  # no NBR data → assume no fire evidence

    # --- Heat mitigation score (0-100) ---
    # Higher canopy = better heat mitigation (higher score = more mitigation = LESS risk).
    canopy = features.get("canopy_proxy")
    if canopy is not None:
        heat_mitigation_score = max(0, min(100, canopy / 0.8 * 100))
    else:
        heat_mitigation_score = 50.0

    # --- Flood risk score (0-100) ---
    # Two components, both from Sentinel-1 SAR VV backscatter (cloud-independent):
    #   chronic: sar_water_freq_5y  -- persistent/recurring water over 5 years
    #   anomaly: sar_flood_anomaly  -- recent water_frac spike above seasonal baseline
    # The anomaly detects sudden flood events missed by the chronic metric when
    # flood months are excluded by the NDSI snow filter (flooded fields look like snow).
    # Not suppressed for urban locations.
    sar_water_freq = features.get("sar_water_freq_5y") or 0.0
    sar_flood_anomaly = features.get("sar_flood_anomaly") or 0.0

    # NDWI optical cross-validation veto applied to both chronic and acute components.
    # Primary path (chronic): if NDWI < 5% and SAR chronic > artifact threshold, veto.
    # This targets structural false positives: coastal SAR windows capturing open ocean,
    # airport runways, or smooth rooftops that chronically mimic water in C-band.
    # Secondary path (acute): if NDWI is confirmed zero (never detected in 5 years) and
    # SAR chronic is in a moderate range (12-50%), veto the acute score too. This catches
    # orbit geometry artifacts in mountain valleys where one orbit track consistently
    # produces specular C-band returns (smooth granite, wet meadow, river at a fixed look
    # angle) while optical never confirms surface water. The anomaly in such cases reflects
    # inter-orbit divergence rather than a genuine temporal flood event.
    _raw_ndwi = features.get("ndwi_wetness_persistence_5y")
    ndwi_pers = _raw_ndwi or 0.0
    chronic_score = sar_water_freq * 100
    ndwi_unconfirmed = ndwi_pers < settings.SAR_NDWI_CORROBORATION_THRESHOLD
    if ndwi_unconfirmed and chronic_score > 0:
        chronic_score *= settings.SAR_NDWI_VETO_FACTOR
    # Scale factor of 2.5: 10% anomaly → 25 pts, 40% → 100 pts.
    # The anomaly signal already represents water above seasonal baseline,
    # so a linear 1:1 mapping (×100) under-weights genuine episodic flood events.
    acute_score = min(100.0, sar_flood_anomaly * 250)
    # When chronic SAR is elevated but NDWI provides no corroboration, the SAR window
    # likely has a systematic artifact (snow/ice/frozen ground). Apply the same veto
    # to acute_score. The effective threshold scales down with snow artifact risk so
    # that high-elevation semi-arid/continental climates need less chronic evidence
    # to trigger the veto (e.g. BSk at 1600m: threshold ~0.26 vs default 0.50).
    snow_artifact_risk = _sar_snow_artifact_risk(climate_code, features.get("elevation_m"))
    effective_artifact_threshold = settings.SAR_CHRONIC_ARTIFACT_THRESHOLD * (
        1.0 - 0.5 * snow_artifact_risk
    )
    # Secondary orbit-geometry artifact veto: NDWI confirmed zero (not None, not trace)
    # and SAR chronic is in moderate range -- optical silence over 5 years is conclusive.
    # _orbit_artifact implies ndwi_unconfirmed (0.0 < 0.05) but is kept as a separate
    # branch for clarity: the primary path gates on high chronic SAR (> 0.45), the
    # secondary path gates on confirmed zero NDWI (> moderate chronic SAR > 0.12).
    _confirmed_zero_ndwi = _raw_ndwi is not None and _raw_ndwi == 0.0
    if ndwi_unconfirmed and sar_water_freq > effective_artifact_threshold:
        acute_score *= settings.SAR_NDWI_VETO_FACTOR
    elif _confirmed_zero_ndwi and sar_water_freq > settings.SAR_ZERO_NDWI_ARTIFACT_THRESHOLD:
        acute_score *= settings.SAR_NDWI_VETO_FACTOR

    # Terrain flash flood: low elevation + significant slope = fast runoff concentration
    elev_m = features.get("elevation_m")
    terrain_flash_score = 0.0
    if (
        elev_m is not None
        and slope_deg is not None
        and elev_m < settings.TERRAIN_FLASH_ELEV_MAX
        and slope_deg > settings.TERRAIN_FLASH_SLOPE_MIN
    ):
        low_elev_factor = (settings.TERRAIN_FLASH_ELEV_MAX - elev_m) / settings.TERRAIN_FLASH_ELEV_MAX
        slope_factor = min(1.0, slope_deg / settings.TERRAIN_FLASH_SLOPE_MAX)
        terrain_flash_score = low_elev_factor * slope_factor * 100

    # SAR observations dominate; terrain is a 50%-weighted potential signal
    flood_risk_score = max(chronic_score, acute_score, terrain_flash_score * 0.5)

    # TPI boost: valley floors / depressions concentrate runoff
    tpi_m_val = features.get("tpi_m")
    if tpi_m_val is not None and tpi_m_val < settings.TERRAIN_TPI_FLOOD_THRESHOLD:
        tpi_boost = min(
            settings.TERRAIN_TPI_FLOOD_MAX_BOOST,
            (-tpi_m_val - abs(settings.TERRAIN_TPI_FLOOD_THRESHOLD)) / 2.0,
        )
        flood_risk_score = min(100.0, flood_risk_score + tpi_boost)

    # Curvature boost: concave terrain (positive Laplacian) collects water
    curvature_val = features.get("curvature")
    if curvature_val is not None and curvature_val > settings.TERRAIN_CURVATURE_THRESHOLD:
        curv_boost = min(
            settings.TERRAIN_CURVATURE_MAX_BOOST,
            curvature_val * settings.TERRAIN_CURVATURE_SCALE,
        )
        flood_risk_score = min(100.0, flood_risk_score + curv_boost)

    # Part A: active flood boost
    if features.get("active_flood"):
        flood_risk_score = min(100.0, flood_risk_score * settings.ACTIVE_FLOOD_BOOST)

    if flood_risk_score > 10:
        driver = "sar_flood_anomaly" if sar_flood_anomaly * 250 >= chronic_score else "sar_water_freq_5y"
        factors.append({
            "name": driver,
            "direction": "positive",
            "weight": w.get("flood", 0.15),
        })

    # --- Heat stress score (0-100) ---
    # TerraClimate-derived: elevated temperature anomaly frequency, warming trend,
    # and high-VPD stress.  Defaults to 50 when TerraClimate data is unavailable.
    tmax_anomaly_freq  = features.get("tmax_anomaly_freq_5y")
    tmax_trend         = features.get("tmax_trend_slope_5y")
    vpd_high_freq      = features.get("vpd_high_freq_5y")

    has_tc = any(v is not None for v in [tmax_anomaly_freq, tmax_trend, vpd_high_freq])
    if has_tc:
        hs_components: list[float] = []
        hs_weights: list[float] = []

        if tmax_anomaly_freq is not None:
            hs_components.append(tmax_anomaly_freq * 100)
            hs_weights.append(0.40)
            if tmax_anomaly_freq > 0.20:
                factors.append({"name": "tmax_anomaly_freq_5y", "direction": "positive", "weight": 0.40})

        if tmax_trend is not None:
            # 0.05 °C/yr → 100 (extreme warming trend).
            trend_component = max(0.0, min(100.0, (tmax_trend / 0.05) * 100))
            hs_components.append(trend_component)
            hs_weights.append(0.30)
            if tmax_trend > 0.03:
                factors.append({"name": "tmax_trend_slope_5y", "direction": "positive", "weight": 0.30})

        if vpd_high_freq is not None:
            hs_components.append(vpd_high_freq * 100)
            hs_weights.append(0.30)
            if vpd_high_freq > 0.25:
                factors.append({"name": "vpd_high_freq_5y", "direction": "positive", "weight": 0.30})

        # Part C: VPD trend slope sub-component
        vpd_trend = features.get("vpd_trend_slope_5y")
        if vpd_trend is not None:
            vpd_slope_score = max(0.0, min(100.0, (vpd_trend / settings.VPD_TREND_HIGH_MIN) * 100))
            hs_components.append(vpd_slope_score)
            hs_weights.append(0.20)

        if hs_components:
            total_hw = sum(hs_weights)
            heat_stress_score: float = (
                sum(c * hw for c, hw in zip(hs_components, hs_weights)) / total_hw
            )
        else:
            heat_stress_score = 50.0

        # Improving VPD trend mitigation (negative slope = atmospheric drought stress declining)
        if vpd_trend is not None and vpd_trend < 0:
            mitig = min(0.15, (-vpd_trend / settings.VPD_TREND_HIGH_MIN) * 0.15)
            heat_stress_score = max(0.0, heat_stress_score * (1.0 - mitig))

        # Part B: tmax momentum amplifier / dampener (progressive above 2×)
        tmax_momentum = features.get("tmax_momentum_ratio_1y")
        if tmax_momentum is not None:
            if tmax_momentum > 1.0:
                excess = tmax_momentum - 1.0
                raw = excess * settings.MOMENTUM_AMP_SCALE + max(0.0, excess - 1.0) * settings.MOMENTUM_AMP_SCALE
                heat_stress_score = min(100.0, heat_stress_score * (1.0 + min(settings.MOMENTUM_AMP_MAX, raw)))
            elif 0.0 < tmax_momentum < 1.0:
                hs_damp = 1.0 - min(settings.MOMENTUM_DAMP_MAX, (1.0 - tmax_momentum) * settings.MOMENTUM_AMP_SCALE)
                heat_stress_score = max(0.0, heat_stress_score * hs_damp)
    else:
        heat_stress_score = 50.0

    # HLI heat stress amplifier: south-facing slopes (NH) experience higher solar load
    if hli_amp > 1.0:
        heat_stress_score = min(100.0, heat_stress_score * hli_amp)

    # --- Landslide risk score (0-100, standalone -- not in composite) ---
    # Slope is the primary driver (shear stress); relief is secondary (slope length).
    # Suppressed for urban locations: GLO-30 is a surface model (DSM) -- building rooftop
    # edges inflate the gradient and produce spurious slope readings in dense urban areas.
    # Landslides are also physically impossible on fully impervious surfaces.
    elev_range_m = features.get("elevation_range_m")
    if is_urban:
        landslide_score = 0.0
    elif slope_deg is not None:
        slope_score = min(100.0, slope_deg / settings.TERRAIN_LANDSLIDE_SLOPE_MAX * 100)
        relief_score = min(100.0, (elev_range_m or 0.0) / settings.TERRAIN_LANDSLIDE_RELIEF_MAX * 100)
        landslide_score = 0.70 * slope_score + 0.30 * relief_score
    else:
        landslide_score = 0.0

    # --- Composite (0-100) ---
    # Formula: 40% climate-zone-weighted average + 60% dominant (max) sub-score.
    # Ensures a single extreme hazard always surfaces instead of being diluted by
    # the weighted average. landslide_score enters the max() only (no rebalancing
    # of climate zone weights needed).
    if is_urban:
        # Urban: heat mitigation (canopy deficit) is one factor among several.
        # It stays in the weighted term to reflect shade/UHI risk, but is excluded
        # from urban_max so that actual hazards (flood, heat stress) drive the
        # composite rather than the structural absence of trees dominating everything.
        urban_weighted = (
            0.30 * (100 - heat_mitigation_score)
            + 0.15 * wetness_score
            + 0.30 * flood_risk_score
            + 0.25 * heat_stress_score
        )
        urban_max = max(
            wetness_score,
            flood_risk_score,
            heat_stress_score,
        )
        composite = 0.40 * urban_weighted + 0.60 * urban_max
    else:
        # Climate-zone-weighted composite. heat_inv = canopy deficit (100 - mitigation).
        weighted_avg = (
            w["drought"]       * drought_score
            + w["wetness"]     * wetness_score
            + w["fire"]        * fire_exposure_score
            + w["heat_inv"]    * (100 - heat_mitigation_score)
            + w["flood"]       * flood_risk_score
            + w["heat_stress"] * heat_stress_score
        )
        dominant = max(
            drought_score,
            wetness_score,
            fire_exposure_score,
            100 - heat_mitigation_score,
            flood_risk_score,
            heat_stress_score,
            landslide_score,
        )
        composite = 0.40 * weighted_avg + 0.60 * dominant

    return ScoreResult(
        drought_score=_clamp(drought_score),
        wetness_score=_clamp(wetness_score),
        fire_exposure_score=_clamp(fire_exposure_score),
        heat_mitigation_score=_clamp(heat_mitigation_score),
        flood_risk_score=_clamp(flood_risk_score),
        heat_stress_score=_clamp(heat_stress_score),
        landslide_risk_score=_clamp(landslide_score),
        composite_score=_clamp(composite),
        top_factors=sorted(factors, key=lambda f: f["weight"], reverse=True)[:3],
        climate_profile=profile,
    )
