from __future__ import annotations

import numpy as np

from src.location_sentinel.compute.indices import (
    compute_bsi,
    compute_nbr,
    compute_ndmi,
    compute_ndsi,
    compute_ndvi,
    compute_ndwi,
    spatial_mean,
)


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


class TestNDMI:
    def test_formula(self):
        nir  = np.array([4000.0, 3000.0])
        swir = np.array([1000.0, 3000.0])
        ndmi = compute_ndmi(nir, swir)
        np.testing.assert_allclose(ndmi, (nir - swir) / (nir + swir))

    def test_high_moisture_positive(self):
        # NIR >> SWIR → good moisture → positive
        assert compute_ndmi(np.array([4000.0]), np.array([500.0]))[0] > 0

    def test_stress_negative(self):
        # SWIR >> NIR → water stress → negative
        assert compute_ndmi(np.array([500.0]), np.array([4000.0]))[0] < 0


class TestNBR:
    def test_formula(self):
        nir   = np.array([4000.0, 500.0])
        swir2 = np.array([500.0, 4000.0])
        nbr = compute_nbr(nir, swir2)
        np.testing.assert_allclose(nbr, (nir - swir2) / (nir + swir2))

    def test_healthy_vegetation_positive(self):
        # High NIR, low SWIR2 → healthy, unburned
        assert compute_nbr(np.array([4000.0]), np.array([300.0]))[0] > 0.3

    def test_burned_negative(self):
        # Low NIR (destroyed cells), high SWIR2 (exposed minerals)
        assert compute_nbr(np.array([300.0]), np.array([4000.0]))[0] < 0


class TestNDSI:
    def test_formula(self):
        green = np.array([3000.0, 500.0])
        swir  = np.array([300.0, 3000.0])
        ndsi = compute_ndsi(green, swir)
        np.testing.assert_allclose(ndsi, (green - swir) / (green + swir))

    def test_snow_high_positive(self):
        # Snow: high green, very low SWIR → NDSI > 0.4
        assert compute_ndsi(np.array([3000.0]), np.array([200.0]))[0] > 0.4

    def test_bare_soil_negative(self):
        # Soil: low green, higher SWIR
        assert compute_ndsi(np.array([800.0]), np.array([2000.0]))[0] < 0


class TestBSI:
    def test_formula(self):
        swir = np.array([2000.0])
        red  = np.array([1500.0])
        nir  = np.array([3000.0])
        blue = np.array([800.0])
        bsi = compute_bsi(swir, red, nir, blue)
        expected = (swir + red - nir - blue) / (swir + red + nir + blue)
        np.testing.assert_allclose(bsi, expected)

    def test_bare_soil_positive(self):
        # High SWIR+Red, low NIR+Blue → exposed soil
        assert compute_bsi(
            np.array([3000.0]), np.array([2500.0]),
            np.array([500.0]),  np.array([300.0]),
        )[0] > 0

    def test_vegetation_negative(self):
        # High NIR, low SWIR+Red → vegetated
        assert compute_bsi(
            np.array([500.0]),  np.array([600.0]),
            np.array([4000.0]), np.array([400.0]),
        )[0] < 0


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
