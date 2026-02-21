from __future__ import annotations

from src.parcel_sentinel.compute.aggregation import Observation, aggregate_monthly


class TestAggregation:
    def test_single_obs_per_month(self):
        obs = [
            Observation(month_key="2024-01", mean_value=0.5, valid_pixel_count=100, cloud_fraction=0.1),
            Observation(month_key="2024-02", mean_value=0.6, valid_pixel_count=100, cloud_fraction=0.05),
        ]
        records = aggregate_monthly(obs)
        assert len(records) == 2
        assert records[0].month == "2024-01"
        assert records[0].mean == 0.5
        assert records[0].obs_count == 1

    def test_multiple_obs_weighted_mean(self):
        obs = [
            Observation(month_key="2024-01", mean_value=0.4, valid_pixel_count=100, cloud_fraction=0.1),
            Observation(month_key="2024-01", mean_value=0.6, valid_pixel_count=300, cloud_fraction=0.05),
        ]
        records = aggregate_monthly(obs)
        assert len(records) == 1
        # Weighted: (0.4*100 + 0.6*300) / 400 = 220/400 = 0.55
        assert records[0].mean == 0.55

    def test_all_none_values(self):
        obs = [
            Observation(month_key="2024-01", mean_value=None, valid_pixel_count=0, cloud_fraction=0.9),
        ]
        records = aggregate_monthly(obs)
        assert len(records) == 1
        assert records[0].mean is None

    def test_sorted_output(self):
        obs = [
            Observation(month_key="2024-03", mean_value=0.3, valid_pixel_count=100, cloud_fraction=0.1),
            Observation(month_key="2024-01", mean_value=0.5, valid_pixel_count=100, cloud_fraction=0.1),
            Observation(month_key="2024-02", mean_value=0.4, valid_pixel_count=100, cloud_fraction=0.1),
        ]
        records = aggregate_monthly(obs)
        months = [r.month for r in records]
        assert months == ["2024-01", "2024-02", "2024-03"]

    def test_empty_input(self):
        records = aggregate_monthly([])
        assert records == []
