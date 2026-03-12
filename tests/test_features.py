from __future__ import annotations

import pytest

from src.location_sentinel.compute.aggregation import MonthlyRecord
from src.location_sentinel.compute.canopy import compute_canopy_proxy_from_series
from src.location_sentinel.compute.features import (
    compute_anomaly_frequency,
    compute_mean,
    compute_quality_score,
    compute_recent_anomaly_ratio,
    compute_trend_slope,
    compute_wetness_persistence,
)


def _make_records(values: list[tuple[str, float | None]]) -> list[MonthlyRecord]:
    return [
        MonthlyRecord(month=m, mean=v, obs_count=1 if v is not None else 0, cloud_fraction=0.1)
        for m, v in values
    ]


class TestTrendSlope:
    def test_flat_series(self):
        records = _make_records([
            ("2020-01", 0.5), ("2020-02", 0.5), ("2020-03", 0.5),
            ("2020-04", 0.5), ("2020-05", 0.5), ("2020-06", 0.5),
        ])
        slope = compute_trend_slope(records)
        assert slope is not None
        assert abs(slope) < 0.01

    def test_increasing_series(self):
        records = _make_records([
            (f"2020-{i:02d}", 0.3 + i * 0.01) for i in range(1, 13)
        ])
        slope = compute_trend_slope(records)
        assert slope is not None
        assert slope > 0

    def test_insufficient_data(self):
        records = _make_records([("2020-01", 0.5), ("2020-02", 0.6)])
        assert compute_trend_slope(records) is None


class TestAnomalyFrequency:
    def test_no_anomalies(self):
        # All values equal, no deviation from climatology
        records = _make_records([
            ("2020-01", 0.5), ("2021-01", 0.5), ("2022-01", 0.5),
        ])
        freq = compute_anomaly_frequency(records, threshold=0.1)
        assert freq == 0.0

    def test_all_anomalies(self):
        # Big drop in second year
        records = _make_records([
            ("2020-01", 0.5), ("2021-01", 0.2),
        ])
        freq = compute_anomaly_frequency(records, threshold=0.1)
        # Climatology for Jan = mean(0.5, 0.2) = 0.35
        # 2020-01: 0.5 - 0.35 = 0.15 > -0.1 -> not anomaly
        # 2021-01: 0.2 - 0.35 = -0.15 < -0.1 -> anomaly
        assert freq == 0.5

    def test_empty(self):
        assert compute_anomaly_frequency([]) is None


class TestWetnessPersistence:
    def test_all_wet(self):
        records = _make_records([("2020-01", 0.1), ("2020-02", 0.2)])
        pers = compute_wetness_persistence(records, threshold=0.0)
        assert pers == 1.0

    def test_none_wet(self):
        records = _make_records([("2020-01", -0.1), ("2020-02", -0.2)])
        pers = compute_wetness_persistence(records, threshold=0.0)
        assert pers == 0.0

    def test_half_wet(self):
        records = _make_records([("2020-01", 0.1), ("2020-02", -0.1)])
        pers = compute_wetness_persistence(records, threshold=0.0)
        assert pers == 0.5


class TestMean:
    def test_basic(self):
        records = _make_records([("2020-01", 0.3), ("2020-02", 0.5)])
        assert compute_mean(records) == 0.4

    def test_with_none(self):
        records = _make_records([("2020-01", 0.3), ("2020-02", None)])
        assert compute_mean(records) == 0.3


class TestQualityScore:
    def test_perfect(self):
        score = compute_quality_score(months_total=60, months_observed=60, mean_cloud_fraction=0.0)
        assert score == 1.0

    def test_half_coverage(self):
        # formula: 0.65 * coverage + 0.35 * clarity = 0.65*0.5 + 0.35*1.0 = 0.675
        score = compute_quality_score(months_total=60, months_observed=30, mean_cloud_fraction=0.0)
        assert abs(score - 0.675) < 0.001

    def test_low_coverage(self):
        # coverage = 12/60 = 0.2; formula: 0.65*0.2 + 0.35*1.0 = 0.48
        score = compute_quality_score(months_total=60, months_observed=12, mean_cloud_fraction=0.0)
        assert abs(score - 0.48) < 0.001

    def test_zero_total(self):
        assert compute_quality_score(0, 0, 0.0) == 0.0


class TestRecentAnomalyRatio:
    def _make_5y(self, base_val: float = 0.5) -> list:
        """60 months of stable values (2020-01 to 2024-12)."""
        return _make_records([
            (f"{2020 + (i // 12)}-{(i % 12) + 1:02d}", base_val)
            for i in range(60)
        ])

    def test_no_historical_anomalies_returns_none(self):
        # Flat series → baseline_freq near zero → None
        records = self._make_5y(0.5)
        result = compute_recent_anomaly_ratio(records, "2024-12", threshold=0.1)
        assert result is None

    def test_ratio_worsening(self):
        # 5y series: 10% anomaly rate overall, but recent 12m have 50% anomaly rate
        records = _make_records([
            (f"{2020 + (i // 12)}-{(i % 12) + 1:02d}", 0.5) for i in range(48)
        ] + [
            # last 12 months: half are severely below climatology
            ("2024-01", 0.3), ("2024-02", 0.5), ("2024-03", 0.3), ("2024-04", 0.5),
            ("2024-05", 0.3), ("2024-06", 0.5), ("2024-07", 0.3), ("2024-08", 0.5),
            ("2024-09", 0.3), ("2024-10", 0.5), ("2024-11", 0.3), ("2024-12", 0.5),
        ])
        result = compute_recent_anomaly_ratio(records, "2024-12", threshold=0.1)
        assert result is not None
        assert result > 1.0  # recent is worse than baseline

    def test_ratio_improving(self):
        # First 3 years: severely low NDVI (0.1); last 2 years: healthy (0.7).
        # Climatology per month ≈ (0.1+0.1+0.1+0.7+0.7)/5 = 0.34.
        # Historical departure: 0.1 - 0.34 = -0.24 < -0.1 → anomalous.
        # Recent departure:     0.7 - 0.34 = +0.36 > -0.1 → not anomalous.
        records = _make_records([
            (f"{2020 + (i // 12)}-{(i % 12) + 1:02d}", 0.1 if i < 36 else 0.7)
            for i in range(60)
        ])
        result = compute_recent_anomaly_ratio(records, "2024-12", threshold=0.1)
        assert result is not None
        assert result == 0.0

    def test_capped_at_5(self):
        # Recent period has massive anomaly rate vs very low baseline
        # Build a series where only 1 month in first 48 was anomalous, but all 12 recent are
        recs = _make_records(
            [("2020-01", 0.3)] +  # 1 anomaly in year 1
            [(f"{2020 + (i // 12)}-{(i % 12) + 1:02d}", 0.5) for i in range(1, 48)] +
            [(f"2024-{m:02d}", 0.3) for m in range(1, 13)]  # all 12 recent are anomalous
        )
        result = compute_recent_anomaly_ratio(recs, "2024-12", threshold=0.1)
        assert result is not None
        assert result <= 5.0

    def test_insufficient_data_returns_none(self):
        records = _make_records([("2020-01", 0.3), ("2020-02", 0.4)])
        assert compute_recent_anomaly_ratio(records, "2020-02") is None

    def test_recent_window_insufficient_returns_none(self):
        # 5y of historical data but only 1 record in recent window
        records = _make_records([
            (f"{2020 + (i // 12)}-{(i % 12) + 1:02d}", 0.3 if i % 6 == 0 else 0.5)
            for i in range(59)
        ] + [("2024-12", 0.3)])
        # date_end is far future so recent window is very small
        result = compute_recent_anomaly_ratio(records, "2019-01", recent_months=1)
        assert result is None


class TestCanopyProxy:
    def test_basic(self):
        # Growing season May-Sep for lat > 33
        records = _make_records([
            ("2020-05", 0.5), ("2020-06", 0.7), ("2020-07", 0.8),
            ("2021-05", 0.6), ("2021-06", 0.75), ("2021-07", 0.85),
        ])
        proxy = compute_canopy_proxy_from_series(records, latitude=40.0)
        # Peaks: 2020=0.8, 2021=0.85, mean=0.825
        assert proxy is not None
        assert abs(proxy - 0.825) < 0.001

    def test_subtropical(self):
        records = _make_records([
            ("2020-03", 0.6), ("2020-07", 0.8), ("2020-11", 0.5),
        ])
        proxy = compute_canopy_proxy_from_series(records, latitude=30.0)
        # All months in subtropical season, peak = 0.8
        assert proxy is not None
        assert abs(proxy - 0.8) < 0.001

    def test_no_growing_season_data(self):
        records = _make_records([("2020-01", 0.3), ("2020-12", 0.2)])
        proxy = compute_canopy_proxy_from_series(records, latitude=40.0)
        assert proxy is None
