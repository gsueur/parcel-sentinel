from __future__ import annotations

from dataclasses import dataclass

from ..config import settings


@dataclass
class ScoreResult:
    drought_score: int
    wetness_score: int
    fire_exposure_score: int
    heat_mitigation_score: int
    composite_score: int
    top_factors: list[dict]


def _clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> int:
    return int(max(lo, min(hi, round(value))))


def compute_scores(features: dict[str, float | None]) -> ScoreResult:
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
    canopy = features.get("canopy_proxy_200m") or features.get("canopy_proxy_50m")
    if canopy is not None:
        heat_mitigation_score = max(0, min(100, canopy / 0.8 * 100))
    else:
        heat_mitigation_score = 50.0

    # --- Composite (0-100) ---
    if is_urban:
        # Urban: heat island (canopy deficit) + flooding are the primary risks.
        composite = (
            0.60 * (100 - heat_mitigation_score)
            + 0.40 * wetness_score
        )
    else:
        # Heat mitigation is inverted: high mitigation reduces composite risk.
        composite = (
            0.35 * drought_score
            + 0.25 * wetness_score
            + 0.20 * fire_exposure_score
            + 0.20 * (100 - heat_mitigation_score)
        )

    return ScoreResult(
        drought_score=_clamp(drought_score),
        wetness_score=_clamp(wetness_score),
        fire_exposure_score=_clamp(fire_exposure_score),
        heat_mitigation_score=_clamp(heat_mitigation_score),
        composite_score=_clamp(composite),
        top_factors=sorted(factors, key=lambda f: f["weight"], reverse=True)[:3],
    )
