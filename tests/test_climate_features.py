from __future__ import annotations

from src.location_sentinel.compute.climate_features import (
    _compute_recent_freq_ratio,
    compute_climate_features,
)


def _make_series(values: list[tuple[int, int, float | None]]) -> dict[tuple[int, int], float | None]:
    return {(y, m): v for y, m, v in values}


class TestRecentFreqRatio:
    def _flat_5y(self, val: float = 30.0) -> dict[tuple[int, int], float | None]:
        """60 months (2020-01 to 2024-12) of a constant value."""
        return _make_series([
            (2020 + (i // 12), (i % 12) + 1, val) for i in range(60)
        ])

    def test_no_baseline_anomalies_returns_none(self):
        series = self._flat_5y()
        result = _compute_recent_freq_ratio(series, "2024-12-31", lambda y, m, v: False)
        assert result is None

    def test_ratio_worsening(self):
        # Anomaly = value > 35. Baseline has a few hot months, recent 12m are mostly hot.
        series = _make_series(
            [(2020 + (i // 12), (i % 12) + 1, 30.0) for i in range(44)]
            + [(2023, m, 40.0) for m in (9, 10, 11, 12)]
            + [(2024, m, 40.0) for m in range(1, 13)]
        )
        result = _compute_recent_freq_ratio(series, "2024-12-31", lambda y, m, v: v > 35)
        assert result is not None
        assert result > 1.0

    def test_future_months_excluded_from_recent_window(self):
        """Regression: cached months after date_end must not enter the recent window.

        The TerraClimate grid-cell cache is shared across locations, so the series
        can contain months beyond this location's date_end. Before the fix, those
        months satisfied (end_abs - month_abs) < 12 because the delta is negative.
        """
        # Baseline 2020-2024: anomaly rate 4/60. Recent window ending 2024-06
        # (12 months: 2023-07..2024-06): zero anomalies.
        # Future months 2024-07..2024-12: all anomalous (cached by another analysis).
        series = _make_series(
            [(2020 + (i // 12), (i % 12) + 1, 30.0) for i in range(54)]
            + [(2024, m, 40.0) for m in (7, 8, 9, 10, 11, 12)]
            + [(2020, 1, 40.0), (2020, 2, 40.0), (2021, 1, 40.0), (2021, 2, 40.0)]
        )
        result = _compute_recent_freq_ratio(series, "2024-06-30", lambda y, m, v: v > 35)
        # Recent window (2023-07..2024-06) has zero anomalies → ratio must be 0,
        # not inflated by the 6 anomalous future months.
        assert result == 0.0

    def test_insufficient_recent_observations_returns_none(self):
        # Only 2 observations fall inside the recent window
        series = _make_series(
            [(2020 + (i // 12), (i % 12) + 1, 30.0 if i % 5 else 40.0) for i in range(50)]
            + [(2024, 5, 30.0), (2024, 6, 30.0)]
        )
        result = _compute_recent_freq_ratio(series, "2025-04-30", lambda y, m, v: v > 35)
        assert result is None


class TestComputeClimateFeatures:
    def _make_monthly(self, n_months: int = 60, start_year: int = 2020):
        """Build {(year, month): value} dicts for tmax/PDSI with seasonal cycle."""
        tmax = {}
        pdsi = {}
        for i in range(n_months):
            y = start_year + i // 12
            m = (i % 12) + 1
            # Seasonal tmax: 10°C winter, 30°C summer
            tmax[(y, m)] = 20.0 + 10.0 * (1 if 5 <= m <= 9 else -1)
            pdsi[(y, m)] = 0.5  # neutral
        return tmax, pdsi

    def test_momentum_not_inflated_by_future_months(self):
        """End-to-end: future hot months in the series must not create false momentum."""
        tmax, pdsi = self._make_monthly()
        # Append 6 months beyond date_end with extreme heat (cache contamination)
        for m in range(7, 13):
            tmax[(2024, m)] = 45.0
            pdsi[(2024, m)] = -5.0

        features = compute_climate_features(
            monthly_series={"tmax": tmax, "PDSI": pdsi},
            date_start="2020-01-01",
            date_end="2024-06-30",
            growing_season_months=[5, 6, 7, 8, 9],
        )
        # tmax momentum: recent window (2023-07..2024-06) has normal seasonal values.
        # Note: with the in-function bound the recent window excludes the future
        # months; the ratio is None (no baseline anomalies among in-window months
        # is also acceptable) or <= 1.0. It must NOT be > 1.
        ratio = features["tmax_momentum_ratio_1y"]
        assert ratio is None or ratio <= 1.0

        pdsi_ratio = features["pdsi_momentum_ratio_1y"]
        assert pdsi_ratio is None or pdsi_ratio <= 1.0

    def test_basic_features_present(self):
        tmax, pdsi = self._make_monthly()
        features = compute_climate_features(
            monthly_series={"tmax": tmax, "PDSI": pdsi},
            date_start="2020-01-01",
            date_end="2024-12-31",
            growing_season_months=[5, 6, 7, 8, 9],
        )
        assert features["tmax_mean_5y"] is not None
        assert features["tmax_summer_mean_5y"] == 30.0
        assert features["pdsi_drought_freq_5y"] == 0.0
