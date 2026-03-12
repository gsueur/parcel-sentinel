from __future__ import annotations

from src.location_sentinel.compute.scoring import (
    climate_profile_label,
    climate_weights_for_code,
    compute_scores,
)


class TestScoring:
    def test_healthy_location(self):
        features = {
            "ndvi_mean_5y": 0.65,
            "ndvi_trend_slope_5y": 0.01,
            "ndvi_anomaly_freq_5y": 0.05,
            "ndwi_wetness_persistence_5y": 0.1,
            "ndmi_moisture_stress_freq_5y": 0.05,
            "nbr_burn_freq_5y": 0.0,
            "canopy_proxy": 0.6,
            "quality_score": 0.9,
        }
        result = compute_scores(features)
        assert result.drought_score < 40
        assert result.wetness_score < 20
        assert result.fire_exposure_score == 0
        assert result.heat_mitigation_score > 60
        assert 0 <= result.composite_score <= 100

    def test_stressed_location(self):
        features = {
            "ndvi_mean_5y": 0.2,
            "ndvi_trend_slope_5y": -0.03,
            "ndvi_anomaly_freq_5y": 0.4,
            "ndwi_wetness_persistence_5y": 0.05,
            "ndmi_moisture_stress_freq_5y": 0.6,
            "nbr_burn_freq_5y": 0.0,
            "canopy_proxy": 0.15,
            "quality_score": 0.7,
        }
        result = compute_scores(features)
        assert result.drought_score > 60
        # composite reflects drought+canopy penalty; no fire data so fire=0 keeps it moderate
        assert result.composite_score > 30

    def test_wet_location(self):
        features = {
            "ndvi_mean_5y": 0.5,
            "ndvi_trend_slope_5y": 0.0,
            "ndvi_anomaly_freq_5y": 0.1,
            "ndwi_wetness_persistence_5y": 0.8,
            "ndmi_moisture_stress_freq_5y": 0.1,
            "canopy_proxy": 0.4,
            "quality_score": 0.85,
        }
        result = compute_scores(features)
        assert result.wetness_score > 70

    def test_fire_exposure(self):
        features = {
            "ndvi_mean_5y": 0.4,
            "nbr_burn_freq_5y": 0.3,   # 30% of months show burn signal → 0.3*350=105 → capped at 100
        }
        result = compute_scores(features)
        assert result.fire_exposure_score == 100

    def test_no_nbr_data_defaults_zero(self):
        # When NBR is missing, fire exposure should default to 0
        features = {"ndvi_mean_5y": 0.5}
        result = compute_scores(features)
        assert result.fire_exposure_score == 0

    def test_missing_features(self):
        features = {}
        result = compute_scores(features)
        assert result.drought_score == 50
        assert result.wetness_score == 50
        assert result.fire_exposure_score == 0
        assert result.composite_score == result.composite_score  # deterministic

    def test_deterministic(self):
        features = {
            "ndvi_mean_5y": 0.42,
            "ndvi_trend_slope_5y": -0.0031,
            "ndvi_anomaly_freq_5y": 0.18,
            "ndwi_wetness_persistence_5y": 0.09,
            "ndmi_moisture_stress_freq_5y": 0.25,
            "nbr_burn_freq_5y": 0.05,
            "canopy_proxy": 0.41,
        }
        r1 = compute_scores(features)
        r2 = compute_scores(features)
        assert r1.drought_score == r2.drought_score
        assert r1.fire_exposure_score == r2.fire_exposure_score
        assert r1.composite_score == r2.composite_score

    def test_urban_drought_zeroed(self):
        features = {
            "is_urban": 1.0,
            "ndvi_mean_5y": 0.10,
            "ndvi_anomaly_freq_5y": 0.5,
            "ndvi_trend_slope_5y": -0.04,
            "ndmi_moisture_stress_freq_5y": 0.6,
            "canopy_proxy": 0.12,
        }
        result = compute_scores(features)
        assert result.drought_score == 0

    def test_urban_fire_zeroed(self):
        features = {
            "is_urban": 1.0,
            "nbr_burn_freq_5y": 0.3,
            "canopy_proxy": 0.12,
        }
        result = compute_scores(features)
        assert result.fire_exposure_score == 0

    def test_urban_composite_formula(self):
        # composite = 0.60*(100-heat_mitigation) + 0.15*wetness + 0.15*flood + 0.10*heat_stress
        # canopy=0.56 → heat_mitigation=0.56/0.8*100=70
        # wetness = 0.20*100 = 20
        # flood = 0 (no SAR data)
        # heat_stress = 50 (default when no TerraClimate data)
        # composite = 0.60*(100-70) + 0.15*20 + 0.15*0 + 0.10*50 = 18+3+0+5 = 26
        features = {
            "is_urban": 1.0,
            "ndwi_wetness_persistence_5y": 0.20,
            "canopy_proxy": 0.56,  # → heat_mitigation = 70
        }
        result = compute_scores(features)
        assert result.heat_mitigation_score == 70
        assert result.wetness_score == 20
        assert result.drought_score == 0
        assert result.fire_exposure_score == 0
        assert result.composite_score == 26  # 0.60*(100-70) + 0.15*20 + 0.15*0 + 0.10*50

    # --- Climate profile tests ---

    def test_climate_weights_arid(self):
        w = climate_weights_for_code("BWh")
        assert w["drought"] == 0.38
        assert w["fire"] == 0.16
        assert abs(sum(w.values()) - 1.0) < 1e-9

    def test_climate_weights_mediterranean(self):
        w = climate_weights_for_code("Csa")
        assert w["fire"] == 0.28
        assert w["drought"] == 0.20

    def test_climate_weights_csb(self):
        # Csb should resolve to the Cs profile, not generic C
        w = climate_weights_for_code("Csb")
        assert w["fire"] == 0.28

    def test_climate_weights_tropical(self):
        w = climate_weights_for_code("Af")
        assert w["wetness"] == 0.30
        assert w["drought"] == 0.07

    def test_climate_weights_fallback_none(self):
        w = climate_weights_for_code(None)
        assert w["drought"] == 0.22
        assert w["wetness"] == 0.16

    def test_climate_weights_fallback_unknown(self):
        w = climate_weights_for_code("XX")
        assert w == climate_weights_for_code(None)

    def test_climate_profile_label(self):
        assert climate_profile_label("Csa") == "Mediterranean"
        assert climate_profile_label("BWh") == "Arid"
        assert climate_profile_label("Af") == "Tropical"
        assert climate_profile_label(None) == "Generic"

    def test_climate_weights_sum_to_one(self):
        for code in ["Af", "BWh", "Csa", "Cfb", "Dfa", "ET", None]:
            w = climate_weights_for_code(code)
            assert abs(sum(w.values()) - 1.0) < 1e-9, f"weights don't sum to 1 for {code}"

    def test_arid_composite_dominated_by_drought(self):
        # Arid profile: drought weight 50% -- a high drought score should drive composite up
        features_high_drought = {
            "ndvi_mean_5y": 0.1,
            "ndvi_anomaly_freq_5y": 0.6,
            "ndvi_trend_slope_5y": -0.04,
            "ndmi_moisture_stress_freq_5y": 0.7,
            "ndwi_wetness_persistence_5y": 0.0,
            "canopy_proxy": 0.2,
        }
        r_arid = compute_scores(features_high_drought, climate_code="BWh")
        r_default = compute_scores(features_high_drought)
        assert r_arid.composite_score > r_default.composite_score
        assert r_arid.climate_profile == "Arid"

    def test_mediterranean_composite_dominated_by_fire(self):
        features_fire = {
            "nbr_burn_freq_5y": 0.5,
            "ndvi_mean_5y": 0.4,
            "ndwi_wetness_persistence_5y": 0.05,
            "canopy_proxy": 0.3,
        }
        r_med = compute_scores(features_fire, climate_code="Csa")
        r_default = compute_scores(features_fire)
        assert r_med.composite_score > r_default.composite_score
        assert r_med.climate_profile == "Mediterranean"

    def test_climate_profile_in_result(self):
        result = compute_scores({"ndvi_mean_5y": 0.5}, climate_code="Dfa")
        assert result.climate_profile == "Continental / Boreal"

    # --- Trend-aware scoring tests (Part A: active boosts) ---

    def test_active_flood_boosts_flood_score(self):
        base = {"sar_water_freq_5y": 0.30, "ndwi_wetness_persistence_5y": 0.10}
        r_no_flag = compute_scores({**base, "active_flood": 0.0})
        r_active = compute_scores({**base, "active_flood": 1.0})
        assert r_active.flood_risk_score > r_no_flag.flood_risk_score

    def test_active_flood_clamps_at_100(self):
        features = {
            "sar_water_freq_5y": 1.0,
            "ndwi_wetness_persistence_5y": 0.50,
            "active_flood": 1.0,
        }
        result = compute_scores(features)
        assert result.flood_risk_score <= 100

    def test_active_drought_boosts_drought_score(self):
        base = {
            "ndvi_mean_5y": 0.25,
            "ndvi_anomaly_freq_5y": 0.35,
            "ndmi_moisture_stress_freq_5y": 0.50,
        }
        r_no_flag = compute_scores({**base, "active_drought": 0.0})
        r_active = compute_scores({**base, "active_drought": 1.0})
        assert r_active.drought_score > r_no_flag.drought_score

    def test_active_drought_suppressed_for_urban(self):
        features = {
            "is_urban": 1.0,
            "ndvi_mean_5y": 0.15,
            "ndvi_anomaly_freq_5y": 0.5,
            "active_drought": 1.0,
        }
        result = compute_scores(features)
        assert result.drought_score == 0  # urban drought stays zeroed regardless of flag

    def test_active_fire_boosts_fire_score(self):
        base = {"nbr_burn_freq_5y": 0.10}
        r_no_flag = compute_scores({**base, "active_fire": 0.0})
        r_active = compute_scores({**base, "active_fire": 1.0})
        assert r_active.fire_exposure_score > r_no_flag.fire_exposure_score

    def test_active_fire_suppressed_for_urban(self):
        features = {"is_urban": 1.0, "nbr_burn_freq_5y": 0.3, "active_fire": 1.0}
        result = compute_scores(features)
        assert result.fire_exposure_score == 0

    # --- Trend-aware scoring tests (Part B: momentum amplifiers) ---

    def test_momentum_boosts_drought(self):
        base = {"ndvi_mean_5y": 0.3, "ndvi_anomaly_freq_5y": 0.25}
        r_no_momentum = compute_scores(base)
        r_momentum = compute_scores({**base, "ndvi_momentum_ratio_1y": 3.0})
        assert r_momentum.drought_score > r_no_momentum.drought_score

    def test_momentum_below_one_dampens(self):
        base = {"ndvi_mean_5y": 0.3, "ndvi_anomaly_freq_5y": 0.25}
        r_no_momentum = compute_scores(base)
        r_improving = compute_scores({**base, "ndvi_momentum_ratio_1y": 0.5})
        assert r_improving.drought_score < r_no_momentum.drought_score

    def test_tmax_momentum_boosts_heat_stress(self):
        base = {"tmax_anomaly_freq_5y": 0.30, "vpd_high_freq_5y": 0.20}
        r_no_momentum = compute_scores(base)
        r_momentum = compute_scores({**base, "tmax_momentum_ratio_1y": 4.0})
        assert r_momentum.heat_stress_score > r_no_momentum.heat_stress_score

    # --- Trend-aware scoring tests (Part C: slope sub-components) ---

    def test_negative_ndmi_trend_raises_drought(self):
        base = {"ndvi_mean_5y": 0.4, "ndmi_moisture_stress_freq_5y": 0.3}
        r_flat = compute_scores({**base, "ndmi_trend_slope_5y": 0.0})
        r_stress = compute_scores({**base, "ndmi_trend_slope_5y": -0.04})
        assert r_stress.drought_score > r_flat.drought_score

    def test_positive_vpd_trend_raises_heat_stress(self):
        base = {"tmax_anomaly_freq_5y": 0.20}
        r_flat = compute_scores({**base, "vpd_trend_slope_5y": 0.0})
        r_rising = compute_scores({**base, "vpd_trend_slope_5y": 0.04})
        assert r_rising.heat_stress_score > r_flat.heat_stress_score

    def test_positive_ndwi_trend_raises_wetness(self):
        base = {"ndwi_wetness_persistence_5y": 0.20}
        r_flat = compute_scores({**base, "ndwi_trend_slope_5y": 0.0})
        r_wetter = compute_scores({**base, "ndwi_trend_slope_5y": 0.01})
        assert r_wetter.wetness_score > r_flat.wetness_score

    def test_negative_pdsi_trend_raises_drought(self):
        base = {"pdsi_drought_freq_5y": 0.20}
        r_flat = compute_scores({**base, "pdsi_trend_slope_5y": 0.0})
        r_drying = compute_scores({**base, "pdsi_trend_slope_5y": -0.3})
        assert r_drying.drought_score > r_flat.drought_score

    # --- Mitigation tests (improving conditions reduce scores) ---

    def test_positive_ndmi_trend_reduces_drought(self):
        base = {"ndvi_mean_5y": 0.3, "ndmi_moisture_stress_freq_5y": 0.40}
        r_flat = compute_scores({**base, "ndmi_trend_slope_5y": 0.0})
        r_improving = compute_scores({**base, "ndmi_trend_slope_5y": 0.04})
        assert r_improving.drought_score < r_flat.drought_score

    def test_positive_pdsi_trend_reduces_drought(self):
        base = {"pdsi_drought_freq_5y": 0.30}
        r_flat = compute_scores({**base, "pdsi_trend_slope_5y": 0.0})
        r_improving = compute_scores({**base, "pdsi_trend_slope_5y": 0.4})
        assert r_improving.drought_score < r_flat.drought_score

    def test_negative_ndwi_trend_reduces_wetness(self):
        base = {"ndwi_wetness_persistence_5y": 0.60}
        r_flat = compute_scores({**base, "ndwi_trend_slope_5y": 0.0})
        r_drying = compute_scores({**base, "ndwi_trend_slope_5y": -0.02})
        assert r_drying.wetness_score < r_flat.wetness_score

    def test_negative_vpd_trend_reduces_heat_stress(self):
        base = {"tmax_anomaly_freq_5y": 0.30, "vpd_high_freq_5y": 0.25}
        r_flat = compute_scores({**base, "vpd_trend_slope_5y": 0.0})
        r_cooling = compute_scores({**base, "vpd_trend_slope_5y": -0.04})
        assert r_cooling.heat_stress_score < r_flat.heat_stress_score

    def test_tmax_momentum_below_one_dampens_heat_stress(self):
        base = {"tmax_anomaly_freq_5y": 0.30, "vpd_high_freq_5y": 0.20}
        r_no_momentum = compute_scores(base)
        r_improving = compute_scores({**base, "tmax_momentum_ratio_1y": 0.4})
        assert r_improving.heat_stress_score < r_no_momentum.heat_stress_score

    def test_improving_conditions_lower_composite(self):
        # Full improving-trend scenario: all recent signals pointing recovery
        stressed = {
            "ndvi_mean_5y": 0.28, "ndvi_anomaly_freq_5y": 0.35, "ndmi_moisture_stress_freq_5y": 0.45,
            "ndwi_wetness_persistence_5y": 0.50, "pdsi_drought_freq_5y": 0.25,
            "tmax_anomaly_freq_5y": 0.30, "vpd_high_freq_5y": 0.20,
        }
        recovering = {
            **stressed,
            "ndvi_momentum_ratio_1y": 0.3,
            "ndmi_momentum_ratio_1y": 0.4,
            "pdsi_momentum_ratio_1y": 0.5,
            "tmax_momentum_ratio_1y": 0.4,
            "ndmi_trend_slope_5y": 0.03,
            "pdsi_trend_slope_5y": 0.3,
            "vpd_trend_slope_5y": -0.04,
            "ndwi_trend_slope_5y": -0.02,
        }
        r_stressed = compute_scores(stressed)
        r_recovering = compute_scores(recovering)
        assert r_recovering.composite_score < r_stressed.composite_score

    def test_absent_slope_features_no_change(self):
        # Existing test features should be unaffected when new keys are absent
        features = {
            "ndvi_mean_5y": 0.42,
            "ndvi_trend_slope_5y": -0.0031,
            "ndvi_anomaly_freq_5y": 0.18,
            "ndwi_wetness_persistence_5y": 0.09,
            "ndmi_moisture_stress_freq_5y": 0.25,
            "nbr_burn_freq_5y": 0.05,
            "canopy_proxy": 0.41,
        }
        r1 = compute_scores(features)
        # Same features but with explicit zero/None momentum and slopes
        features2 = {**features, "ndvi_momentum_ratio_1y": None, "ndmi_momentum_ratio_1y": None}
        r2 = compute_scores(features2)
        assert r1.drought_score == r2.drought_score
        assert r1.composite_score == r2.composite_score

    def test_scores_in_range(self):
        features = {
            "ndvi_mean_5y": 0.42,
            "ndvi_trend_slope_5y": -0.0031,
            "ndvi_anomaly_freq_5y": 0.18,
            "ndwi_wetness_persistence_5y": 0.09,
            "ndmi_moisture_stress_freq_5y": 0.3,
            "nbr_burn_freq_5y": 0.1,
            "canopy_proxy": 0.41,
        }
        result = compute_scores(features)
        for score in [
            result.drought_score, result.wetness_score,
            result.fire_exposure_score, result.heat_mitigation_score,
            result.composite_score,
        ]:
            assert 0 <= score <= 100
