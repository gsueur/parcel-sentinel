from __future__ import annotations

import numpy as np
import pytest

from src.location_sentinel.compute.sar_features import (
    compute_sar_flood_anomaly,
    compute_sar_water_frequency,
    compute_water_fraction,
)


def _months(start: str, n: int) -> list[str]:
    """Generate n consecutive YYYY-MM keys starting at `start`."""
    y, m = int(start[:4]), int(start[5:7])
    keys = []
    for _ in range(n):
        keys.append(f"{y:04d}-{m:02d}")
        m += 1
        if m > 12:
            m, y = 1, y + 1
    return keys


def _scenes(
    fracs: list[float], orbit: int = 8, start: str = "2020-01"
) -> list[tuple[str, float, int]]:
    """Build (month_key, water_frac, rel_orbit) tuples over consecutive months."""
    return [(mk, f, orbit) for mk, f in zip(_months(start, len(fracs)), fracs)]


class TestComputeWaterFraction:
    def test_basic_fraction(self):
        # 30 water pixels (DN < 75), 70 land pixels
        arr = np.array([50.0] * 30 + [100.0] * 70, dtype=np.float32)
        assert compute_water_fraction(arr) == pytest.approx(0.30)

    def test_nodata_excluded_from_denominator(self):
        # 50 nodata (DN = 0), 25 water, 25 land → fraction over valid pixels only
        arr = np.array([0.0] * 50 + [50.0] * 25 + [100.0] * 25, dtype=np.float32)
        assert compute_water_fraction(arr) == pytest.approx(0.50)

    def test_all_nodata_returns_none(self):
        arr = np.zeros(100, dtype=np.float32)
        assert compute_water_fraction(arr) is None

    def test_flat_mask_excludes_steep_false_water(self):
        # Steep half mimics water (low DN from geometric artefact); flat half is land.
        arr = np.array([50.0] * 50 + [100.0] * 50, dtype=np.float32)
        flat_mask = np.array([False] * 50 + [True] * 50)
        # Without mask: 50% water. With mask: steep pixels excluded → 0% water.
        assert compute_water_fraction(arr) == pytest.approx(0.50)
        assert compute_water_fraction(arr, flat_mask=flat_mask) == pytest.approx(0.0)

    def test_flat_mask_all_excluded_returns_none(self):
        arr = np.array([50.0] * 10, dtype=np.float32)
        flat_mask = np.zeros(10, dtype=bool)
        assert compute_water_fraction(arr, flat_mask=flat_mask) is None


class TestComputeSarWaterFrequency:
    def test_empty_returns_none(self):
        assert compute_sar_water_frequency([]) is None

    def test_dry_inland_zero(self):
        # All scenes far below both thresholds: median 0.025, MAD 0.005,
        # anomaly threshold = max(0.025 + 2×0.005, 0.05) = 0.05 → nothing elevated.
        scenes = _scenes([0.02, 0.03, 0.02, 0.03, 0.02, 0.03, 0.02, 0.03])
        assert compute_sar_water_frequency(scenes) == 0.0

    def test_open_water_absolute_dominates(self):
        # Lake/bay: every scene above the 35% absolute threshold → 1.0,
        # regardless of consecutive-month requirements.
        scenes = _scenes([0.65, 0.70, 0.72, 0.80, 0.68, 0.75, 0.60, 0.78])
        assert compute_sar_water_frequency(scenes) == pytest.approx(1.0)

    def test_chronic_water_needs_no_consecutive_months(self):
        # Absolute path applies even with calendar gaps between scenes
        # (permanent water is real by definition).
        scenes = [
            ("2020-01", 0.60, 8),
            ("2020-04", 0.62, 8),  # 3-month gap
            ("2020-09", 0.58, 8),  # 5-month gap
        ]
        assert compute_sar_water_frequency(scenes) == pytest.approx(1.0)

    def test_isolated_anomalies_suppressed(self):
        # Two isolated flood-like scenes (Mar, Jun): elevated above the MAD
        # threshold but not calendar-consecutive → suppressed by min_consecutive=2.
        scenes = _scenes([0.05, 0.05, 0.30, 0.05, 0.05, 0.30, 0.05, 0.05])
        assert compute_sar_water_frequency(scenes) == 0.0

    def test_consecutive_flood_event_detected(self):
        # Same anomaly magnitude as above, but the two flood scenes are in
        # adjacent calendar months (Mar-Apr) → counted: 2/8.
        scenes = _scenes([0.05, 0.05, 0.30, 0.32, 0.05, 0.05, 0.05, 0.05])
        assert compute_sar_water_frequency(scenes) == pytest.approx(2 / 8)

    def test_calendar_gap_breaks_consecutive_run(self):
        # Two elevated scenes 2 calendar months apart (missing scene between
        # them) do not form a consecutive run → suppressed.
        scenes = [
            ("2020-01", 0.05, 8),
            ("2020-02", 0.05, 8),
            ("2020-03", 0.30, 8),
            # 2020-04 missing (e.g. no acquisition)
            ("2020-05", 0.32, 8),
            ("2020-06", 0.05, 8),
            ("2020-07", 0.05, 8),
            ("2020-08", 0.05, 8),
            ("2020-09", 0.05, 8),
        ]
        assert compute_sar_water_frequency(scenes) == 0.0

    def test_consecutive_run_across_year_boundary(self):
        # Dec-Jan flood spans the year boundary → still consecutive.
        scenes = (
            _scenes([0.05] * 6, start="2020-06")  # Jun-Nov baseline
            + [("2020-12", 0.30, 8), ("2021-01", 0.32, 8)]
            + _scenes([0.05] * 4, start="2021-02")
        )
        assert compute_sar_water_frequency(scenes) == pytest.approx(2 / 12)

    def test_orbit_stratification_prevents_cross_orbit_false_positive(self):
        # Orbit 8 has a low backscatter baseline (2%), orbit 110 a higher one (20%)
        # purely from look-angle difference. Pooled, orbit 110's normal scenes would
        # sit far above the pooled median and read as a months-long flood event.
        # Stratified per orbit, both are flat → 0.
        scenes = _scenes([0.02] * 20, orbit=8) + _scenes([0.20] * 6, orbit=110)
        assert compute_sar_water_frequency(scenes) == 0.0

    def test_max_across_orbits(self):
        # One dry track, one chronically wet track → max wins.
        scenes = _scenes([0.02] * 10, orbit=8) + _scenes([0.60] * 10, orbit=110)
        assert compute_sar_water_frequency(scenes) == pytest.approx(1.0)

    def test_single_scene_above_absolute(self):
        assert compute_sar_water_frequency([("2020-01", 0.50, 8)]) == pytest.approx(1.0)

    def test_single_scene_below_thresholds(self):
        # median = 0.10 = value, anomaly threshold = max(0.10, 0.05) = 0.10, not exceeded
        assert compute_sar_water_frequency([("2020-01", 0.10, 8)]) == pytest.approx(0.0)

    def test_all_identical_below_absolute(self):
        # MAD = 0 → threshold = median itself → nothing strictly above it
        scenes = _scenes([0.10] * 10)
        assert compute_sar_water_frequency(scenes) == pytest.approx(0.0)

    def test_anomaly_floor_suppresses_instrument_noise(self):
        # Sub-percent fluctuations: with the 5% floor nothing is elevated;
        # with the floor disabled, the 0.4% scene counts as an "anomaly".
        scenes = _scenes([0.001, 0.002, 0.003, 0.004, 0.003, 0.002])
        assert compute_sar_water_frequency(scenes, min_consecutive=1) == 0.0
        no_floor = compute_sar_water_frequency(scenes, min_anomaly=0.0, min_consecutive=1)
        assert no_floor > 0.0

    def test_custom_mad_k(self):
        # median = 0.12, MAD = 0.04.
        # mad_k=2 → threshold max(0.20, 0.05): the 0.30/0.32 pair (consecutive) counts → 2/7.
        # mad_k=10 → threshold 0.52: nothing elevated → 0.
        scenes = _scenes([0.05, 0.08, 0.10, 0.12, 0.15, 0.30, 0.32])
        assert compute_sar_water_frequency(scenes, mad_k=2.0) == pytest.approx(2 / 7)
        assert compute_sar_water_frequency(scenes, mad_k=10.0) == 0.0


class TestComputeSarFloodAnomaly:
    def test_empty_returns_none(self):
        assert compute_sar_flood_anomaly([], "2024-03-31") is None

    def test_no_recent_scenes_returns_none(self):
        # All scenes are historical relative to date_end → nothing to evaluate
        scenes = [("2021-03", 0.05, 8), ("2022-03", 0.05, 8), ("2023-03", 0.06, 8)]
        assert compute_sar_flood_anomaly(scenes, "2025-12-31") is None

    def test_recent_flood_detected(self):
        # Recent March water fraction far above the orbit+March baseline
        scenes = [
            ("2021-03", 0.05, 8),
            ("2022-03", 0.05, 8),
            ("2023-03", 0.06, 8),
            ("2024-03", 0.50, 8),  # recent
        ]
        result = compute_sar_flood_anomaly(scenes, "2024-03-31")
        assert result == pytest.approx(0.50 - 0.05)

    def test_recent_below_baseline_is_zero(self):
        # Recent scene drier than baseline → anomaly clamped to 0
        scenes = [
            ("2021-03", 0.20, 8),
            ("2022-03", 0.22, 8),
            ("2023-03", 0.21, 8),
            ("2024-03", 0.05, 8),  # recent, below baseline
        ]
        assert compute_sar_flood_anomaly(scenes, "2024-03-31") == 0.0

    def test_insufficient_baseline_returns_none(self):
        # Only one historical scene for the (orbit, month) AND for the fallback → None
        scenes = [
            ("2023-03", 0.05, 8),
            ("2024-03", 0.50, 8),  # recent
        ]
        assert compute_sar_flood_anomaly(scenes, "2024-03-31") is None

    def test_orbit_fallback_when_orbit_baseline_sparse(self):
        # Recent scene is from orbit 110, which has only 1 historical March scene.
        # Falls back to the all-orbit March baseline (4 scenes, median 0.05).
        scenes = [
            ("2021-03", 0.05, 8),
            ("2022-03", 0.05, 8),
            ("2023-03", 0.06, 8),
            ("2023-03", 0.04, 110),
            ("2024-03", 0.40, 110),  # recent
        ]
        result = compute_sar_flood_anomaly(scenes, "2024-03-31")
        assert result == pytest.approx(0.40 - 0.05)

    def test_peak_anomaly_across_recent_scenes(self):
        # Two recent scenes (Feb + Mar within the 2-month window): peak anomaly returned
        scenes = [
            ("2021-02", 0.05, 8),
            ("2022-02", 0.05, 8),
            ("2021-03", 0.05, 8),
            ("2022-03", 0.05, 8),
            ("2024-02", 0.15, 8),  # recent, mild anomaly (0.10)
            ("2024-03", 0.45, 8),  # recent, strong anomaly (0.40)
        ]
        result = compute_sar_flood_anomaly(scenes, "2024-03-31")
        assert result == pytest.approx(0.40)

    def test_recent_window_spans_year_boundary(self):
        # date_end in January: recent window = {Jan, previous Dec}
        scenes = [
            ("2021-12", 0.05, 8),
            ("2022-12", 0.05, 8),
            ("2023-12", 0.45, 8),  # recent (Dec of prior year)
        ]
        result = compute_sar_flood_anomaly(scenes, "2024-01-31")
        assert result == pytest.approx(0.45 - 0.05)

    def test_seasonal_baseline_no_false_positive(self):
        # Site floods every March (rice paddy / seasonal wetland). Recent March
        # matches the March baseline → no anomaly, despite being far above the
        # annual median.
        scenes = [
            ("2021-03", 0.60, 8),
            ("2022-03", 0.62, 8),
            ("2023-03", 0.61, 8),
            ("2021-08", 0.02, 8),
            ("2022-08", 0.03, 8),
            ("2023-08", 0.02, 8),
            ("2024-03", 0.61, 8),  # recent: normal seasonal flood
        ]
        assert compute_sar_flood_anomaly(scenes, "2024-03-31") == 0.0
