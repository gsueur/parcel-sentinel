from __future__ import annotations

from statistics import median

import pytest

from src.location_sentinel.compute.sar_features import compute_sar_water_frequency


class TestComputeSarWaterFrequency:
    def test_empty_returns_none(self):
        assert compute_sar_water_frequency([]) is None

    def test_dry_inland_all_below_absolute_threshold(self):
        # Classic dry location: all scenes well below 35% -- both thresholds return 0
        fracs = [0.02, 0.05, 0.03, 0.04, 0.06, 0.01, 0.03, 0.02]
        assert compute_sar_water_frequency(fracs) == 0.0

    def test_open_water_absolute_dominates(self):
        # Large lake: all scenes at 60-90%, absolute freq = 1.0 dominates
        fracs = [0.65, 0.70, 0.72, 0.80, 0.68, 0.75, 0.60, 0.78]
        assert compute_sar_water_frequency(fracs) == pytest.approx(1.0)

    def test_relative_wins_for_moderate_flood_cluster(self):
        # A location with a low median (~10%) but a cluster of moderate flood
        # scenes at 28-34% -- above relative threshold (10+15=25%) but below
        # the absolute threshold (35%).  Relative freq beats absolute.
        low    = [0.08, 0.10, 0.09, 0.11, 0.07] * 6   # 30 scenes, median ≈ 9%
        mid    = [0.28, 0.30, 0.32, 0.33, 0.34] * 4   # 20 scenes above relative, below absolute
        high   = [0.40, 0.38]                           # 2 scenes above both
        fracs  = low + mid + high  # 52 scenes

        loc_med = median(fracs)
        relative_threshold = loc_med + 0.15
        assert relative_threshold < 0.35, "test precondition: relative threshold must be below absolute"

        absolute_freq = sum(1 for f in fracs if f > 0.35) / len(fracs)
        relative_freq = sum(1 for f in fracs if f > relative_threshold) / len(fracs)

        result = compute_sar_water_frequency(fracs)
        assert result == pytest.approx(max(absolute_freq, relative_freq))
        assert relative_freq > absolute_freq, "relative should dominate for this distribution"
        assert result > absolute_freq

    def test_coastal_lagoon_absolute_wins_when_baseline_high(self):
        # Near-water baseline at ~22%: median + 0.15 = 37% > absolute 35%.
        # Absolute threshold (35%) is lower -- it catches the spikes first.
        # Both frequencies are equal here; absolute wins (or they tie).
        baseline = [0.22] * 30
        spikes   = [0.38, 0.40, 0.42] * 4   # 12 scenes above both thresholds
        fracs    = baseline + spikes          # 42 scenes, median = 0.22

        loc_med = median(fracs)
        assert loc_med + 0.15 > 0.35, "test precondition: relative threshold exceeds absolute"

        result = compute_sar_water_frequency(fracs)
        absolute_freq = sum(1 for f in fracs if f > 0.35) / len(fracs)
        # When relative threshold > absolute, absolute freq >= relative freq,
        # so result == absolute_freq
        assert result == pytest.approx(absolute_freq)

    def test_montpellier_like_distribution(self):
        # Mirrors BeachHouse data: ~60% of scenes below 20% (median ≈ 15%),
        # cluster at 30-34% (sub-35% absolute, above 30% relative), few at 35-42%.
        low  = [0.11, 0.14, 0.13, 0.16, 0.18, 0.12, 0.15, 0.10] * 9   # 72 scenes
        mid  = [0.31, 0.32, 0.33, 0.34] * 4                             # 16 scenes (sub-threshold)
        high = [0.39, 0.40, 0.41, 0.38, 0.42, 0.40, 0.39, 0.40,
                0.38, 0.41, 0.40, 0.40]                                  # 12 scenes
        fracs = low + mid + high  # 100 scenes

        loc_med = median(fracs)
        relative_threshold = loc_med + 0.15
        # Confirm the relative threshold falls below 0.35 (key structural condition)
        assert relative_threshold < 0.35

        absolute_freq = sum(1 for f in fracs if f > 0.35) / len(fracs)
        relative_freq = sum(1 for f in fracs if f > relative_threshold) / len(fracs)

        result = compute_sar_water_frequency(fracs)
        assert result == pytest.approx(relative_freq)    # relative wins
        assert result > absolute_freq                    # score is meaningfully higher

    def test_single_scene_above_absolute(self):
        assert compute_sar_water_frequency([0.50]) == pytest.approx(1.0)

    def test_single_scene_below_both(self):
        # Single scene at 0.10: absolute=0, relative: median=0.10, threshold=0.25, 0 scenes
        assert compute_sar_water_frequency([0.10]) == pytest.approx(0.0)

    def test_all_identical_above_absolute(self):
        # All at 0.50: absolute=1.0; relative threshold=0.50+0.15=0.65, relative=0.0
        # max(1.0, 0.0) = 1.0
        assert compute_sar_water_frequency([0.50] * 10) == pytest.approx(1.0)

    def test_all_identical_below_absolute(self):
        # All at 0.10: absolute=0; relative threshold=0.25, relative=0.0
        assert compute_sar_water_frequency([0.10] * 10) == pytest.approx(0.0)

    def test_result_is_max_of_both(self):
        fracs = [0.05, 0.06, 0.07, 0.25, 0.30]
        loc_med = median(fracs)
        absolute_freq = sum(1 for f in fracs if f > 0.35) / len(fracs)
        relative_freq = sum(1 for f in fracs if f > loc_med + 0.15) / len(fracs)
        assert compute_sar_water_frequency(fracs) == pytest.approx(max(absolute_freq, relative_freq))

    def test_custom_threshold_and_delta(self):
        fracs = [0.10, 0.15, 0.20, 0.50, 0.60]
        result = compute_sar_water_frequency(fracs, threshold=0.45, adaptive_delta=0.20)
        loc_med = median(fracs)
        absolute_freq = sum(1 for f in fracs if f > 0.45) / 5
        relative_freq = sum(1 for f in fracs if f > loc_med + 0.20) / 5
        assert result == pytest.approx(max(absolute_freq, relative_freq))

    def test_zero_delta_relative_is_median_split(self):
        # With delta=0, relative threshold = median itself;
        # roughly half the scenes are above median.
        fracs = [0.05, 0.08, 0.10, 0.12, 0.15]
        # median = 0.10; relative threshold = 0.10; scenes > 0.10: [0.12, 0.15] = 2/5
        result = compute_sar_water_frequency(fracs, adaptive_delta=0.0)
        assert result == pytest.approx(2 / 5)
