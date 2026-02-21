from __future__ import annotations

import numpy as np

from src.location_sentinel.raster.masking import apply_scl_mask, mask_band


class TestSCLMask:
    def test_basic_mask(self, synthetic_scl):
        mask, stats = apply_scl_mask(synthetic_scl)

        # First row (64 pixels) is cloud (9) -> invalid
        # Row 1, cols 0-2 (3 pixels) is shadow (3) -> invalid
        # Rest is vegetation (4) -> valid
        assert stats.total_pixel_count == 64 * 64  # 4096
        assert stats.valid_pixel_count == 4096 - 64 - 3  # 4029
        assert 0.015 < stats.cloud_fraction < 0.018

    def test_all_valid(self):
        scl = np.full((5, 5), 4, dtype=np.uint8)
        mask, stats = apply_scl_mask(scl)
        assert stats.valid_pixel_count == 25
        assert stats.cloud_fraction == 0.0
        assert mask.all()

    def test_all_cloud(self):
        scl = np.full((5, 5), 9, dtype=np.uint8)
        mask, stats = apply_scl_mask(scl)
        assert stats.valid_pixel_count == 0
        assert stats.cloud_fraction == 1.0
        assert not mask.any()

    def test_custom_valid_classes(self):
        scl = np.array([[4, 5, 6, 7, 8]])
        mask, stats = apply_scl_mask(scl, valid_classes=[4, 5])
        assert stats.valid_pixel_count == 2


class TestMaskBand:
    def test_mask_band(self):
        band = np.array([1.0, 2.0, 3.0, 4.0], dtype=np.float32)
        valid = np.array([True, False, True, False])
        result = mask_band(band, valid)
        assert result[0] == 1.0
        assert np.isnan(result[1])
        assert result[2] == 3.0
        assert np.isnan(result[3])
