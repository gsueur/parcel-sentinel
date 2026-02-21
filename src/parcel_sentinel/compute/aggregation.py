from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field


@dataclass
class Observation:
    """A single scene observation for a metric."""
    month_key: str  # "YYYY-MM"
    mean_value: float | None
    valid_pixel_count: int
    cloud_fraction: float


@dataclass
class MonthlyRecord:
    """Aggregated monthly record for a metric."""
    month: str
    mean: float | None
    obs_count: int
    cloud_fraction: float


def aggregate_monthly(observations: list[Observation]) -> list[MonthlyRecord]:
    """Aggregate per-scene observations to monthly records.

    Uses weighted mean by valid pixel count when multiple scenes exist per month.
    """
    by_month: dict[str, list[Observation]] = defaultdict(list)
    for obs in observations:
        by_month[obs.month_key].append(obs)

    records: list[MonthlyRecord] = []
    for month_key in sorted(by_month.keys()):
        month_obs = by_month[month_key]

        # Filter out observations with no valid data
        valid_obs = [o for o in month_obs if o.mean_value is not None and o.valid_pixel_count > 0]

        if not valid_obs:
            records.append(MonthlyRecord(
                month=month_key,
                mean=None,
                obs_count=len(month_obs),
                cloud_fraction=_mean_cloud(month_obs),
            ))
            continue

        # Weighted mean by valid pixel count
        total_weight = sum(o.valid_pixel_count for o in valid_obs)
        weighted_sum = sum(o.mean_value * o.valid_pixel_count for o in valid_obs)
        mean_val = weighted_sum / total_weight if total_weight > 0 else None

        records.append(MonthlyRecord(
            month=month_key,
            mean=round(mean_val, 6) if mean_val is not None else None,
            obs_count=len(valid_obs),
            cloud_fraction=round(_mean_cloud(valid_obs), 4),
        ))

    return records


def _mean_cloud(obs: list[Observation]) -> float:
    if not obs:
        return 0.0
    return sum(o.cloud_fraction for o in obs) / len(obs)
