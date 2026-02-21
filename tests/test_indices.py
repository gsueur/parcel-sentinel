from __future__ import annotations

import numpy as np

from src.parcel_sentinel.compute.indices import compute_ndvi, compute_ndwi, spatial_mean


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
        # McFeeters: (GREEN - NIR) / (GREEN + NIR)
        # Water: GREEN >> NIR → positive; vegetation: NIR >> GREEN → negative
        green = np.array([3000.0, 1000.0])
        nir   = np.array([1000.0, 4000.0])
        ndwi = compute_ndwi(green, nir)
        expected = (green - nir) / (green + nir)
        np.testing.assert_allclose(ndwi, expected)

    def test_water_positive(self):
        # Water: high green reflectance, low NIR → NDWI > 0
        green = np.array([3000.0])
        nir   = np.array([500.0])
        ndwi = compute_ndwi(green, nir)
        assert ndwi[0] > 0

    def test_vegetation_negative(self):
        # Vegetation: high NIR, low green → NDWI < 0
        green = np.array([800.0])
        nir   = np.array([4000.0])
        ndwi = compute_ndwi(green, nir)
        assert ndwi[0] < 0


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
