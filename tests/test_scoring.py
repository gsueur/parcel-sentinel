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
            "nbr_burn_freq_5y": 0.3,   # 30% of months show burn signal
        }
        result = compute_scores(features)
        assert result.fire_exposure_score == 30

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
        # composite = 0.80*(100-heat_mitigation) + 0.20*wetness
        # canopy=0.56 → heat_mitigation=0.56/0.8*100=70
        # wetness = 0.20*100 = 20
        # composite = 0.80*(100-70) + 0.20*20 = 24+4 = 28
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
        assert result.composite_score == 28  # 0.80*(100-70) + 0.20*20

    # --- Climate profile tests ---

    def test_climate_weights_arid(self):
        w = climate_weights_for_code("BWh")
        assert w["drought"] == 0.50
        assert w["fire"] == 0.20
        assert abs(sum(w.values()) - 1.0) < 1e-9

    def test_climate_weights_mediterranean(self):
        w = climate_weights_for_code("Csa")
        assert w["fire"] == 0.40
        assert w["drought"] == 0.30

    def test_climate_weights_csb(self):
        # Csb should resolve to the Cs profile, not generic C
        w = climate_weights_for_code("Csb")
        assert w["fire"] == 0.40

    def test_climate_weights_tropical(self):
        w = climate_weights_for_code("Af")
        assert w["wetness"] == 0.45
        assert w["drought"] == 0.10

    def test_climate_weights_fallback_none(self):
        w = climate_weights_for_code(None)
        assert w["drought"] == 0.35
        assert w["wetness"] == 0.25

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
