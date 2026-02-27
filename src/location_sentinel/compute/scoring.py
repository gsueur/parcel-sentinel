from __future__ import annotations

from dataclasses import dataclass, field

from ..config import settings

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
    composite_score: int
    top_factors: list[dict]
    climate_profile: str = field(default="Generic")


def _clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> int:
    return int(max(lo, min(hi, round(value))))


def compute_scores(features: dict[str, float | None], climate_code: str | None = None) -> ScoreResult:
    """Compute risk sub-scores and composite from derived features.

    All scores are 0-100. Higher = more risk (except heat_mitigation where higher = more mitigation).
    Deterministic, versioned as risk-v1.1.0.

    Sub-scores:
    - drought_score:       NDVI anomaly frequency + trend + mean + NDMI moisture stress
    - wetness_score:       NDWI surface water persistence
    - fire_exposure_score: NBR burn frequency over the lookback period
    - heat_mitigation:     Canopy proxy (higher = more shade = lower heat risk)
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
        drought_components.append(pdsi_drought * 100)
        drought_weights.append(0.25)
        if pdsi_drought > 0.15:
            factors.append({"name": "pdsi_drought_freq_5y", "direction": "positive", "weight": 0.25})

    if is_urban:
        drought_score = 0.0
    elif drought_components:
        total_w = sum(drought_weights)
        drought_score = sum(c * wt for c, wt in zip(drought_components, drought_weights)) / total_w
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
    flood_risk_score = max(sar_water_freq * 100, sar_flood_anomaly * 100)

    # NDWI optical cross-validation veto:
    # If S2 optical shows no persistent surface water (ndwi_wetness_persistence
    # below threshold) but SAR shows a significant water fraction, the two sensors
    # contradict each other. This happens at coastal locations (ocean in the SAR
    # window), airport runways, or large smooth rooftops -- all produce specular
    # C-band backscatter that mimics water but are invisible as water in optical.
    # Apply a strong discount factor; the score is not zeroed in case of partial
    # genuine flooding that the NDWI threshold misses.
    ndwi_pers = features.get("ndwi_wetness_persistence_5y") or 0.0
    if ndwi_pers < settings.SAR_NDWI_CORROBORATION_THRESHOLD and flood_risk_score > 0:
        flood_risk_score *= settings.SAR_NDWI_VETO_FACTOR

    if flood_risk_score > 10:
        driver = "sar_flood_anomaly" if sar_flood_anomaly * 100 >= sar_water_freq * 100 else "sar_water_freq_5y"
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

        if hs_components:
            total_hw = sum(hs_weights)
            heat_stress_score: float = (
                sum(c * hw for c, hw in zip(hs_components, hs_weights)) / total_hw
            )
        else:
            heat_stress_score = 50.0
    else:
        heat_stress_score = 50.0

    # --- Composite (0-100) ---
    if is_urban:
        # Urban: canopy deficit dominates; wetness, flood, and heat stress are secondary.
        # Climate zone weights are irrelevant on impervious surfaces.
        composite = (
            0.60 * (100 - heat_mitigation_score)
            + 0.15 * wetness_score
            + 0.15 * flood_risk_score
            + 0.10 * heat_stress_score
        )
    else:
        # Climate-zone-weighted composite. heat_inv = canopy deficit (100 - mitigation).
        composite = (
            w["drought"]     * drought_score
            + w["wetness"]   * wetness_score
            + w["fire"]      * fire_exposure_score
            + w["heat_inv"]  * (100 - heat_mitigation_score)
            + w["flood"]     * flood_risk_score
            + w["heat_stress"] * heat_stress_score
        )

    return ScoreResult(
        drought_score=_clamp(drought_score),
        wetness_score=_clamp(wetness_score),
        fire_exposure_score=_clamp(fire_exposure_score),
        heat_mitigation_score=_clamp(heat_mitigation_score),
        flood_risk_score=_clamp(flood_risk_score),
        heat_stress_score=_clamp(heat_stress_score),
        composite_score=_clamp(composite),
        top_factors=sorted(factors, key=lambda f: f["weight"], reverse=True)[:3],
        climate_profile=profile,
    )
