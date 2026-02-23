from __future__ import annotations

from dataclasses import dataclass, field

from ..config import settings

# ---------------------------------------------------------------------------
# Climate-zone weight profiles for the composite score
# ---------------------------------------------------------------------------
# Keys: drought, wetness, fire, heat_inv (= 100 - heat_mitigation_score), flood
# All five weights must sum to 1.0.
# Resolution order: "Cs" prefix first, then major letter, then "default".
_CLIMATE_WEIGHTS: dict[str, dict[str, float]] = {
    "A":       {"drought": 0.08, "wetness": 0.37, "fire": 0.10, "heat_inv": 0.25, "flood": 0.20},
    "B":       {"drought": 0.45, "wetness": 0.05, "fire": 0.20, "heat_inv": 0.25, "flood": 0.05},
    "Cs":      {"drought": 0.25, "wetness": 0.08, "fire": 0.35, "heat_inv": 0.17, "flood": 0.15},
    "C":       {"drought": 0.20, "wetness": 0.20, "fire": 0.15, "heat_inv": 0.25, "flood": 0.20},
    "D":       {"drought": 0.15, "wetness": 0.15, "fire": 0.30, "heat_inv": 0.25, "flood": 0.15},
    "E":       {"drought": 0.08, "wetness": 0.17, "fire": 0.05, "heat_inv": 0.55, "flood": 0.15},
    "default": {"drought": 0.28, "wetness": 0.20, "fire": 0.17, "heat_inv": 0.20, "flood": 0.15},
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
    # Combines NDVI vegetation health with NDMI leaf moisture stress.
    anomaly_freq = features.get("ndvi_anomaly_freq_5y")
    trend_slope  = features.get("ndvi_trend_slope_5y")
    ndvi_mean    = features.get("ndvi_mean_5y")
    ndmi_stress  = features.get("ndmi_moisture_stress_freq_5y")

    drought_components: list[float] = []
    drought_weights: list[float] = []

    if anomaly_freq is not None:
        drought_components.append(anomaly_freq * 100)
        drought_weights.append(0.25)
        if anomaly_freq > 0.15:
            factors.append({"name": "ndvi_anomaly_freq_5y", "direction": "positive", "weight": 0.25})

    if trend_slope is not None:
        # Negative slope = drying. Map [-0.05, 0.05] → [100, 0]
        slope_score = max(0, min(100, (0.05 - trend_slope) / 0.10 * 100))
        drought_components.append(slope_score)
        drought_weights.append(0.25)
        if trend_slope < -0.005:
            factors.append({"name": "ndvi_trend_slope_5y", "direction": "negative", "weight": 0.25})

    if ndvi_mean is not None:
        # Lower NDVI = more drought stress. Map [0, 0.8] → [100, 0]
        mean_score = max(0, min(100, (0.8 - ndvi_mean) / 0.8 * 100))
        drought_components.append(mean_score)
        drought_weights.append(0.20)

    if ndmi_stress is not None:
        # Fraction of months with vegetation moisture stress. Map [0, 1] → [0, 100]
        drought_components.append(ndmi_stress * 100)
        drought_weights.append(0.30)
        if ndmi_stress > 0.2:
            factors.append({"name": "ndmi_moisture_stress_freq_5y", "direction": "positive", "weight": 0.30})

    if is_urban:
        drought_score = 0.0
    elif drought_components:
        total_w = sum(drought_weights)
        drought_score = sum(c * w for c, w in zip(drought_components, drought_weights)) / total_w
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
    # Fraction of months where NBR indicates burn signal (NBR < 0.1).
    # 0 = no fire history; 100 = burned nearly every month (extreme).
    nbr_burn_freq = features.get("nbr_burn_freq_5y")
    if is_urban:
        fire_exposure_score = 0.0
    elif nbr_burn_freq is not None:
        fire_exposure_score = nbr_burn_freq * 100
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
    if flood_risk_score > 10:
        driver = "sar_flood_anomaly" if sar_flood_anomaly * 100 >= sar_water_freq * 100 else "sar_water_freq_5y"
        factors.append({
            "name": driver,
            "direction": "positive",
            "weight": w.get("flood", 0.15),
        })

    # --- Composite (0-100) ---
    if is_urban:
        # Urban: canopy deficit dominates; wetness and flood are secondary.
        # Climate zone weights are irrelevant on impervious surfaces.
        composite = (
            0.70 * (100 - heat_mitigation_score)
            + 0.15 * wetness_score
            + 0.15 * flood_risk_score
        )
    else:
        # Climate-zone-weighted composite. Heat mitigation is inverted:
        # high canopy = lower heat contribution to composite risk.
        composite = (
            w["drought"]  * drought_score
            + w["wetness"]  * wetness_score
            + w["fire"]     * fire_exposure_score
            + w["heat_inv"] * (100 - heat_mitigation_score)
            + w["flood"]    * flood_risk_score
        )

    return ScoreResult(
        drought_score=_clamp(drought_score),
        wetness_score=_clamp(wetness_score),
        fire_exposure_score=_clamp(fire_exposure_score),
        heat_mitigation_score=_clamp(heat_mitigation_score),
        flood_risk_score=_clamp(flood_risk_score),
        composite_score=_clamp(composite),
        top_factors=sorted(factors, key=lambda f: f["weight"], reverse=True)[:3],
        climate_profile=profile,
    )
