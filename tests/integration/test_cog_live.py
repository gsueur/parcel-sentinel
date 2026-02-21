from __future__ import annotations

import os

import numpy as np
import pytest
from shapely.geometry import Polygon

from src.parcel_sentinel.raster.masking import apply_scl_mask
from src.parcel_sentinel.raster.reader import read_scene_bands
from src.parcel_sentinel.stac.client import search_scenes

pytestmark = pytest.mark.skipif(
    not os.environ.get("RUN_INTEGRATION_TESTS"),
    reason="Set RUN_INTEGRATION_TESTS=1 to run",
)

AOI = Polygon([
    [-77.0365, 38.8977],
    [-77.0355, 38.8977],
    [-77.0355, 38.8967],
    [-77.0365, 38.8967],
    [-77.0365, 38.8977],
])


def _get_bounds_in_scene_crs(item) -> tuple[float, float, float, float]:
    import pyproj
    from src.parcel_sentinel.geometry.reproject import reproject_geometry
    epsg = item.properties.get("proj:epsg")
    if epsg is None:
        code = item.properties.get("proj:code", "")
        if code.upper().startswith("EPSG:"):
            epsg = int(code.split(":")[1])
    if epsg:
        wgs84 = pyproj.CRS.from_epsg(4326)
        scene_crs = pyproj.CRS.from_epsg(epsg)
        return reproject_geometry(AOI, wgs84, scene_crs).bounds
    return AOI.bounds


class TestCOGLive:
    async def test_read_bands(self):
        result = search_scenes(AOI, "2024-06-01", "2024-06-30", max_scenes_per_month=1)
        assert len(result.scenes) > 0

        scene = result.scenes[0]
        item = scene.item
        bounds = _get_bounds_in_scene_crs(item)

        scene_data = await read_scene_bands(item, bounds, band_keys=["B04", "B08", "SCL"])

        assert "B04" in scene_data.bands
        assert "B08" in scene_data.bands
        assert "SCL" in scene_data.bands
        assert scene_data.shape_10m == (64, 64)
        assert scene_data.bands["B04"].shape == (64, 64)
        assert scene_data.bands["B08"].shape == (64, 64)
        assert scene_data.bands["SCL"].shape == (64, 64)

    async def test_scl_mask_on_real_data(self):
        result = search_scenes(AOI, "2024-06-01", "2024-06-30", max_scenes_per_month=1)
        scene = result.scenes[0]
        item = scene.item
        bounds = _get_bounds_in_scene_crs(item)

        scene_data = await read_scene_bands(item, bounds, band_keys=["SCL"])
        assert "SCL" in scene_data.bands
        assert scene_data.bands["SCL"].shape == (64, 64)

        mask, stats = apply_scl_mask(scene_data.bands["SCL"])
        assert stats.total_pixel_count == 64 * 64
        assert 0.0 <= stats.cloud_fraction <= 1.0
