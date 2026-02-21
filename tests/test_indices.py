from __future__ import annotations

import numpy as np

from src.parcel_sentinel.compute.indices import compute_ndvi, compute_ndwi_gao, spatial_mean


class TestNDVI:
    def test_basic_ndvi(self):
        nir = np.array([4000.0, 3000.0, 2000.0])
        red = np.array([1000.0, 1000.0, 1000.0])
        ndvi = compute_ndvi(nir, red)
        expected = (nir - red) / (nir + red)
        np.testing.assert_allclose(ndvi, expected)

    def test_ndvi_range(self, synthetic_nir, synthetic_red):
        ndvi = compute_ndvi(synthetic_nir, synthetic_red)
        assert np.nanmin(ndvi) >= -1.0
        assert np.nanmax(ndvi) <= 1.0

    def test_ndvi_with_nan(self):
        nir = np.array([4000.0, np.nan, 2000.0])
        red = np.array([1000.0, 1000.0, np.nan])
        ndvi = compute_ndvi(nir, red)
        assert not np.isnan(ndvi[0])
        assert np.isnan(ndvi[1])
        assert np.isnan(ndvi[2])

    def test_ndvi_zero_denominator(self):
        nir = np.array([0.0])
        red = np.array([0.0])
        ndvi = compute_ndvi(nir, red)
        assert np.isnan(ndvi[0])


class TestNDWI:
    def test_basic_ndwi(self):
        nir = np.array([4000.0, 3000.0])
        swir = np.array([2000.0, 2000.0])
        ndwi = compute_ndwi_gao(nir, swir)
        expected = (nir - swir) / (nir + swir)
        np.testing.assert_allclose(ndwi, expected)


class TestSpatialMean:
    def test_normal(self):
        arr = np.array([1.0, 2.0, 3.0])
        assert spatial_mean(arr) == 2.0

    def test_all_nan(self):
        arr = np.array([np.nan, np.nan])
        assert spatial_mean(arr) is None

    def test_partial_nan(self):
        arr = np.array([1.0, np.nan, 3.0])
        assert spatial_mean(arr) == 2.0
