from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from src.location_sentinel.app import create_app
from src.location_sentinel.compute.aggregation import MonthlyRecord
from src.location_sentinel.models.common import QualityInfo

SAMPLE_GEOJSON = {
    "type": "Point",
    "coordinates": [-77.036, 38.897],
}


@pytest.fixture
def client():
    app = create_app()
    with TestClient(app) as c:
        yield c


class TestDateValidation:
    def test_impossible_date_rejected(self, client):
        resp = client.post("/v1/location/features", json={
            "geometry": SAMPLE_GEOJSON,
            "date_start": "1788-22-85",
            "date_end": "8414-06-78",
            "metrics": ["ndvi"],
        })
        assert resp.status_code == 422

    def test_start_after_end_rejected(self, client):
        resp = client.post("/v1/location/timeseries", json={
            "geometry": SAMPLE_GEOJSON,
            "date_start": "2024-06-01",
            "date_end": "2024-01-01",
            "metrics": ["ndvi"],
        })
        assert resp.status_code == 422

    def test_before_sentinel2_rejected(self, client):
        resp = client.post("/v1/location/features", json={
            "geometry": SAMPLE_GEOJSON,
            "date_start": "2010-01-01",
            "date_end": "2015-01-01",
            "metrics": ["ndvi"],
        })
        assert resp.status_code == 422

    def test_future_date_rejected(self, client):
        resp = client.post("/v1/location/score", json={
            "geometry": SAMPLE_GEOJSON,
            "date_end": "2099-01-01",
        })
        assert resp.status_code == 422


class TestHealth:
    def test_health(self, client):
        resp = client.get("/v1/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] in ("ok", "degraded")


class TestTimeseries:
    @patch("src.location_sentinel.routes.timeseries.run_timeseries")
    def test_timeseries_success(self, mock_run, client):
        mock_run.return_value = (
            "sha256:abc123",
            {
                "ndvi": [
                    MonthlyRecord(month="2024-01", mean=0.45, obs_count=1, cloud_fraction=0.1),
                    MonthlyRecord(month="2024-02", mean=0.50, obs_count=1, cloud_fraction=0.08),
                ],
            },
            QualityInfo(months_total=2, months_observed=2, mean_cloud_fraction=0.09),
        )

        resp = client.post("/v1/location/timeseries", json={
            "geometry": SAMPLE_GEOJSON,
            "date_start": "2024-01-01",
            "date_end": "2024-02-28",
            "metrics": ["ndvi"],
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["location_key"] == "sha256:abc123"
        assert len(data["series"]["ndvi"]) == 2
        assert data["series"]["ndvi"][0]["month"] == "2024-01"
        assert data["map_links"] is not None
        assert data["map_links"]["thumbnail_url"].endswith(".png")

    @patch("src.location_sentinel.routes.timeseries.run_timeseries")
    def test_timeseries_no_scenes(self, mock_run, client):
        mock_run.side_effect = ValueError("No scenes found")
        resp = client.post("/v1/location/timeseries", json={
            "geometry": SAMPLE_GEOJSON,
            "date_start": "2024-01-01",
            "date_end": "2024-02-28",
            "metrics": ["ndvi"],
            "force_recompute": True,
        })
        assert resp.status_code == 422


class TestFeatures:
    @patch("src.location_sentinel.routes.features.run_features")
    def test_features_success(self, mock_run, client):
        mock_run.return_value = (
            "sha256:abc123",
            {
                "ndvi_mean_5y": 0.42,
                "ndvi_trend_slope_5y": -0.003,
                "ndvi_anomaly_freq_5y": 0.18,
                "quality_score": 0.87,
            },
            QualityInfo(months_total=60, months_observed=55, mean_cloud_fraction=0.12),
        )

        resp = client.post("/v1/location/features", json={
            "geometry": SAMPLE_GEOJSON,
            "date_start": "2019-01-01",
            "date_end": "2024-01-31",
            "metrics": ["ndvi"],
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "ndvi_mean_5y" in data["features"]
        assert data["quality"]["months_observed"] == 55
        assert data["map_links"] is not None
        assert data["map_links"]["geojson_io_url"].startswith("https://geojson.io/")


class TestScore:
    @patch("src.location_sentinel.routes.score.run_score")
    def test_score_success(self, mock_run, client):
        from src.location_sentinel.compute.scoring import ScoreResult
        from unittest.mock import MagicMock
        mock_quality = MagicMock()
        mock_quality.model_dump.return_value = {"months_total": 60, "months_observed": 55, "mean_cloud_fraction": 0.1, "flags": []}
        mock_run.return_value = (
            "sha256:abc123",
            ScoreResult(
                drought_score=62,
                wetness_score=28,
                fire_exposure_score=15,
                heat_mitigation_score=71,
                composite_score=54,
                top_factors=[
                    {"name": "ndvi_trend_slope_5y", "direction": "negative", "weight": 0.35},
                ],
            ),
            {"ndvi_mean_5y": 0.42},  # features
            mock_quality,             # quality
            "2019-01-31",             # date_start
            {"ndvi": [{"month": "2019-01", "mean": 0.42, "obs": 1, "cloud": 0.05}]},  # series dict
        )

        resp = client.post("/v1/location/score", json={
            "geometry": SAMPLE_GEOJSON,
            "date_end": "2024-01-31",
            "lookback_years": 5,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["scores"]["drought_score"] == 62
        assert data["scores"]["composite_score"] == 54
        assert len(data["explain"]["top_factors"]) == 1
        assert data["map_links"] is not None
        assert "sha256:" in data["map_links"]["thumbnail_url"]
