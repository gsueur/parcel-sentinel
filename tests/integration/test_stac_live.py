from __future__ import annotations

import os

import pytest
from shapely.geometry import Polygon

from src.location_sentinel.stac.client import search_scenes

pytestmark = pytest.mark.skipif(
    not os.environ.get("RUN_INTEGRATION_TESTS"),
    reason="Set RUN_INTEGRATION_TESTS=1 to run",
)

# Small AOI in Virginia
AOI = Polygon([
    [-77.0365, 38.8977],
    [-77.0355, 38.8977],
    [-77.0355, 38.8967],
    [-77.0365, 38.8967],
    [-77.0365, 38.8977],
])


class TestSTACLive:
    def test_search_returns_scenes(self):
        result = search_scenes(
            AOI,
            date_start="2024-06-01",
            date_end="2024-06-30",
            max_scenes_per_month=2,
        )
        assert result.total_items_found > 0
        assert len(result.scenes) > 0
        assert result.scenes[0].month_key == "2024-06"
        # Earth Search items carry common-name asset keys
        item = result.scenes[0].item
        assert "red" in item.assets
        assert "nir" in item.assets
        assert "scl" in item.assets

    def test_search_empty_date_range(self):
        result = search_scenes(
            AOI,
            date_start="2030-01-01",
            date_end="2030-01-31",
        )
        assert result.total_items_found == 0
