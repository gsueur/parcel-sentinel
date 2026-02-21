from __future__ import annotations

import pytest

from src.location_sentinel.compute.aggregation import MonthlyRecord
from src.location_sentinel.compute.canopy import compute_canopy_proxy_from_series
from src.location_sentinel.compute.features import (
    compute_anomaly_frequency,
    compute_mean,
    compute_quality_score,
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
        score = compute_quality_score(months_total=60, months_observed=30, mean_cloud_fraction=0.0)
        assert score == 0.5

    def test_low_coverage(self):
        # 20% coverage: confidence = 0.2/0.5 = 0.4
        # quality = 0.2 * 1.0 * 0.4 = 0.08
        score = compute_quality_score(months_total=60, months_observed=12, mean_cloud_fraction=0.0)
        assert abs(score - 0.08) < 0.01

    def test_zero_total(self):
        assert compute_quality_score(0, 0, 0.0) == 0.0


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
