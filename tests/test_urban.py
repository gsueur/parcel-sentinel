from __future__ import annotations

from src.location_sentinel.compute.urban import detect_urban


class TestDetectUrban:
    def test_urban_true(self):
        features = {
            "bsi_bare_soil_freq_5y": 0.90,  # 90% of months BSI > 0 → impervious
            "ndvi_mean_5y": 0.10,
            "canopy_proxy": 0.12,
        }
        assert detect_urban(features) is True

    def test_urban_false_rural(self):
        features = {
            "bsi_bare_soil_freq_5y": 0.04,  # 4% → vegetated (e.g. Yellowstone)
            "ndvi_mean_5y": 0.55,
            "canopy_proxy": 0.65,
        }
        assert detect_urban(features) is False

    def test_urban_false_missing_bsi_freq(self):
        # Missing bsi_bare_soil_freq_5y → safe default: non-urban
        features = {
            "ndvi_mean_5y": 0.10,
            "canopy_proxy": 0.12,
        }
        assert detect_urban(features) is False

    def test_urban_false_missing_ndvi(self):
        features = {
            "bsi_bare_soil_freq_5y": 0.90,
            "canopy_proxy": 0.12,
        }
        assert detect_urban(features) is False

    def test_urban_true_no_canopy(self):
        # No canopy data → canopy_flag is True → still detected as urban if bsi+ndvi hold
        features = {
            "bsi_bare_soil_freq_5y": 0.90,
            "ndvi_mean_5y": 0.10,
        }
        assert detect_urban(features) is True

    def test_urban_false_high_ndvi(self):
        # BSI freq threshold met but NDVI too high → not urban
        features = {
            "bsi_bare_soil_freq_5y": 0.90,
            "ndvi_mean_5y": 0.40,
            "canopy_proxy": 0.12,
        }
        assert detect_urban(features) is False

    def test_urban_false_low_bsi_freq(self):
        # NDVI threshold met but BSI frequency too low → not urban
        features = {
            "bsi_bare_soil_freq_5y": 0.20,  # below 50% threshold
            "ndvi_mean_5y": 0.10,
            "canopy_proxy": 0.12,
        }
        assert detect_urban(features) is False
