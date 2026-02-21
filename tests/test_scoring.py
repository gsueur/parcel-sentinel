from __future__ import annotations

from src.parcel_sentinel.compute.scoring import compute_scores


class TestScoring:
    def test_healthy_parcel(self):
        features = {
            "ndvi_mean_5y": 0.65,
            "ndvi_trend_slope_5y": 0.01,
            "ndvi_anomaly_freq_5y": 0.05,
            "ndwi_wetness_persistence_5y": 0.1,
            "canopy_proxy_200m": 0.6,
            "quality_score": 0.9,
        }
        result = compute_scores(features)
        # Low drought, low wetness, good canopy
        assert result.drought_score < 40
        assert result.wetness_score < 20
        assert result.heat_mitigation_score > 60
        assert 0 <= result.composite_score <= 100

    def test_stressed_parcel(self):
        features = {
            "ndvi_mean_5y": 0.2,
            "ndvi_trend_slope_5y": -0.03,
            "ndvi_anomaly_freq_5y": 0.4,
            "ndwi_wetness_persistence_5y": 0.05,
            "canopy_proxy_200m": 0.15,
            "quality_score": 0.7,
        }
        result = compute_scores(features)
        assert result.drought_score > 60
        assert result.composite_score > 50

    def test_wet_parcel(self):
        features = {
            "ndvi_mean_5y": 0.5,
            "ndvi_trend_slope_5y": 0.0,
            "ndvi_anomaly_freq_5y": 0.1,
            "ndwi_wetness_persistence_5y": 0.8,
            "canopy_proxy_200m": 0.4,
            "quality_score": 0.85,
        }
        result = compute_scores(features)
        assert result.wetness_score > 70

    def test_missing_features(self):
        features = {}
        result = compute_scores(features)
        # Should default to 50 for unknown
        assert result.drought_score == 50
        assert result.wetness_score == 50
        assert result.composite_score == 50

    def test_deterministic(self):
        features = {
            "ndvi_mean_5y": 0.42,
            "ndvi_trend_slope_5y": -0.0031,
            "ndvi_anomaly_freq_5y": 0.18,
            "ndwi_wetness_persistence_5y": 0.09,
            "canopy_proxy_200m": 0.41,
        }
        r1 = compute_scores(features)
        r2 = compute_scores(features)
        assert r1.drought_score == r2.drought_score
        assert r1.composite_score == r2.composite_score

    def test_scores_in_range(self):
        features = {
            "ndvi_mean_5y": 0.42,
            "ndvi_trend_slope_5y": -0.0031,
            "ndvi_anomaly_freq_5y": 0.18,
            "ndwi_wetness_persistence_5y": 0.09,
            "canopy_proxy_200m": 0.41,
        }
        result = compute_scores(features)
        for score in [result.drought_score, result.wetness_score,
                      result.heat_mitigation_score, result.composite_score]:
            assert 0 <= score <= 100
