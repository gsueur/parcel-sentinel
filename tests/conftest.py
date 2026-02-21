from __future__ import annotations

import os
import tempfile

import numpy as np
import pytest
from shapely.geometry import Polygon, Point, mapping


@pytest.fixture(autouse=True)
def _use_temp_duckdb(tmp_path, monkeypatch):
    """Route DuckDB to a temp file so tests don't conflict with a running server."""
    db_path = str(tmp_path / "test.duckdb")
    monkeypatch.setenv("DUCKDB_PATH", db_path)
    # Also patch the already-imported settings and store instances
    from src.parcel_sentinel.config import settings
    monkeypatch.setattr(settings, "DUCKDB_PATH", db_path)
    from src.parcel_sentinel.storage.duckdb_store import store
    store._db_path = db_path


# Small residential parcel in suburban Virginia (CONUS)
SAMPLE_POLYGON_COORDS = [
    [-77.0365, 38.8977],
    [-77.0355, 38.8977],
    [-77.0355, 38.8967],
    [-77.0365, 38.8967],
    [-77.0365, 38.8977],
]

SAMPLE_POLYGON = Polygon(SAMPLE_POLYGON_COORDS)

SAMPLE_GEOJSON = {
    "type": "Polygon",
    "coordinates": [SAMPLE_POLYGON_COORDS],
}

SAMPLE_POINT_GEOJSON = {
    "type": "Point",
    "coordinates": [-77.0360, 38.8972],
}


@pytest.fixture
def sample_polygon():
    return SAMPLE_POLYGON


@pytest.fixture
def sample_geojson():
    return SAMPLE_GEOJSON


@pytest.fixture
def sample_point_geojson():
    return SAMPLE_POINT_GEOJSON


@pytest.fixture
def synthetic_nir():
    """64x64 NIR band with values typical of vegetation."""
    rng = np.random.default_rng(42)
    return rng.uniform(2000, 4000, (64, 64)).astype(np.float32)


@pytest.fixture
def synthetic_red():
    """64x64 RED band with values typical of vegetation."""
    rng = np.random.default_rng(43)
    return rng.uniform(500, 1500, (64, 64)).astype(np.float32)


@pytest.fixture
def synthetic_swir():
    """64x64 SWIR band."""
    rng = np.random.default_rng(44)
    return rng.uniform(1000, 3000, (64, 64)).astype(np.float32)


@pytest.fixture
def synthetic_scl():
    """64x64 SCL band. Mostly vegetation (4,5) with some cloud (9)."""
    scl = np.full((64, 64), 4, dtype=np.uint8)
    scl[0, :] = 9  # First row is cloud
    scl[1, 0:3] = 3  # Some cloud shadow
    return scl
