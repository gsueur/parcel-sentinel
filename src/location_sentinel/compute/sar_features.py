from __future__ import annotations

from collections import defaultdict
from statistics import median

import numpy as np

from ..config import settings


def compute_water_fraction(vv_dn: np.ndarray) -> float | None:
    """Compute fraction of water pixels in a VV backscatter array.

    Water pixels: DN < SAR_WATER_DN_THRESHOLD AND DN > 0 (exclude nodata).
    Returns None if no valid pixels exist.
    """
    valid_mask = vv_dn > 0
    valid_count = int(valid_mask.sum())
    if valid_count == 0:
        return None
    water_mask = (vv_dn < settings.SAR_WATER_DN_THRESHOLD) & valid_mask
    return float(water_mask.sum()) / valid_count


def compute_sar_water_frequency(
    water_fracs: list[float],
    threshold: float = settings.SAR_MIN_WATER_PIXEL_FRACTION,
    adaptive_delta: float = settings.SAR_RELATIVE_FLOOD_DELTA,
) -> float | None:
    """Fraction of scenes exceeding the flood threshold.

    Two thresholds are evaluated and the higher frequency returned:

    1. Absolute: scenes where water_frac > ``threshold`` (fixed 35%).
       Works well for open-water and inland locations.

    2. Relative: scenes where water_frac > median(all_fracs) + ``adaptive_delta``.
       Handles near-water locations (coastal lagoons, river banks) whose
       baseline water fraction already sits at 15-25%, making the fixed
       threshold too strict to detect genuine above-baseline flood episodes.

    Returns None for empty input.
    """
    if not water_fracs:
        return None
    n = len(water_fracs)
    absolute_freq = sum(1 for f in water_fracs if f > threshold) / n
    loc_median = median(water_fracs)
    relative_freq = sum(1 for f in water_fracs if f > loc_median + adaptive_delta) / n
    return float(max(absolute_freq, relative_freq))


def compute_sar_flood_anomaly(
    scene_fracs: list[tuple[str, float]],
    date_end: str,
    recent_months: int = 2,
    min_baseline_count: int = 2,
) -> float | None:
    """Anomaly-based flood detection: compare recent water_frac to seasonal baseline.

    Uses ALL scene fracs (no snow suppression) to avoid excluding flood months that
    happen to trigger the S2 NDSI snow filter (flooded fields and snow look similar
    in optical). Compares each recent scene to the historical median for the same
    calendar month across previous years.

    Args:
        scene_fracs: list of (month_key "YYYY-MM", water_frac) for all scenes.
        date_end: end of the analysis window "YYYY-MM-DD".
        recent_months: how many of the most recent calendar months count as "recent".
        min_baseline_count: minimum number of historical scenes required to compute
            a baseline for a given calendar month.

    Returns:
        Peak anomaly (max water_frac - seasonal_median) in recent window,
        clamped to [0, 1]. Returns None if insufficient data.
    """
    if not scene_fracs:
        return None

    # Build the set of recent calendar month keys
    end_year, end_month = int(date_end[:4]), int(date_end[5:7])
    recent_month_keys: set[str] = set()
    y, m = end_year, end_month
    for _ in range(recent_months):
        recent_month_keys.add(f"{y:04d}-{m:02d}")
        m -= 1
        if m == 0:
            m = 12
            y -= 1

    # Separate recent observations from historical baseline data
    historical_by_cal: defaultdict[int, list[float]] = defaultdict(list)
    recent_pairs: list[tuple[int, float]] = []  # (calendar_month, water_frac)

    for month_key, wf in scene_fracs:
        cal_month = int(month_key[5:7])  # extract MM from "YYYY-MM"
        if month_key in recent_month_keys:
            recent_pairs.append((cal_month, wf))
        else:
            historical_by_cal[cal_month].append(wf)

    if not recent_pairs:
        return None

    # For each recent observation compute anomaly vs same-month historical median
    anomalies: list[float] = []
    for cal_month, wf in recent_pairs:
        hist = historical_by_cal.get(cal_month, [])
        if len(hist) >= min_baseline_count:
            baseline = median(hist)
            anomalies.append(max(0.0, wf - baseline))

    if not anomalies:
        return None

    return round(min(max(anomalies), 1.0), 4)
