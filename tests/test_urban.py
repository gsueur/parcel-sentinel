from __future__ import annotations

from src.location_sentinel.compute.urban import detect_urban


class TestDetectUrban:
    def test_urban_true(self):
        features = {
            "bsi_mean_5y": 0.15,
            "ndvi_mean_5y": 0.10,
            "canopy_proxy_200m": 0.12,
        }
        assert detect_urban(features) is True

    def test_urban_false_rural(self):
        features = {
            "bsi_mean_5y": -0.05,
            "ndvi_mean_5y": 0.55,
            "canopy_proxy_200m": 0.65,
        }
        assert detect_urban(features) is False

    def test_urban_false_missing_bsi(self):
        # Missing bsi → safe default: non-urban
        features = {
            "ndvi_mean_5y": 0.10,
            "canopy_proxy_200m": 0.12,
        }
        assert detect_urban(features) is False

    def test_urban_false_missing_ndvi(self):
        features = {
            "bsi_mean_5y": 0.15,
            "canopy_proxy_200m": 0.12,
        }
        assert detect_urban(features) is False

    def test_urban_true_no_canopy(self):
        # No canopy data → canopy_flag is True → still detected as urban if bsi+ndvi hold
        features = {
            "bsi_mean_5y": 0.15,
            "ndvi_mean_5y": 0.10,
        }
        assert detect_urban(features) is True

    def test_urban_false_high_ndvi(self):
        # BSI threshold met but NDVI too high → not urban
        features = {
            "bsi_mean_5y": 0.15,
            "ndvi_mean_5y": 0.40,
            "canopy_proxy_200m": 0.12,
        }
        assert detect_urban(features) is False

    def test_urban_false_low_bsi(self):
        # NDVI threshold met but BSI too low → not urban
        features = {
            "bsi_mean_5y": 0.02,
            "ndvi_mean_5y": 0.10,
            "canopy_proxy_200m": 0.12,
        }
        assert detect_urban(features) is False
