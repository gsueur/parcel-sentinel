from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from src.parcel_sentinel.app import create_app

pytestmark = pytest.mark.skipif(
    not os.environ.get("RUN_INTEGRATION_TESTS"),
    reason="Set RUN_INTEGRATION_TESTS=1 to run",
)

SAMPLE_GEOJSON = {
    "type": "Polygon",
    "coordinates": [[
        [-77.0365, 38.8977],
        [-77.0355, 38.8977],
        [-77.0355, 38.8967],
        [-77.0365, 38.8967],
        [-77.0365, 38.8977],
    ]],
}


@pytest.fixture
def client():
    app = create_app()
    with TestClient(app) as c:
        yield c


class TestE2E:
    def test_timeseries_e2e(self, client):
        resp = client.post("/v1/parcel/timeseries", json={
            "geometry": SAMPLE_GEOJSON,
            "date_start": "2024-06-01",
            "date_end": "2024-08-31",
            "metrics": ["ndvi"],
            "max_scenes_per_month": 1,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["parcel_key"].startswith("sha256:")
        assert "ndvi" in data["series"]
        for rec in data["series"]["ndvi"]:
            if rec["mean"] is not None:
                assert -1.0 <= rec["mean"] <= 1.0

    def test_features_e2e(self, client):
        resp = client.post("/v1/parcel/features", json={
            "geometry": SAMPLE_GEOJSON,
            "date_start": "2024-01-01",
            "date_end": "2024-12-31",
            "metrics": ["ndvi"],
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "ndvi_mean_5y" in data["features"]

    def test_score_e2e(self, client):
        resp = client.post("/v1/parcel/score", json={
            "geometry": SAMPLE_GEOJSON,
            "date_end": "2024-12-31",
            "lookback_years": 1,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "drought_score" in data["scores"]
        assert 0 <= data["scores"]["composite_score"] <= 100
