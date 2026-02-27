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


def _mad(fracs: list[float], loc_median: float) -> float:
    """Median absolute deviation."""
    return median(abs(f - loc_median) for f in fracs)


def _orbit_water_frequency(
    fracs: list[float],
    threshold: float,
    mad_k: float,
    min_anomaly: float,
) -> float:
    """Compute water frequency for a single orbital pass.

    Two thresholds evaluated; higher frequency returned:
    1. Absolute: fraction of scenes where water_frac > threshold.
       Catches chronically wet locations (lakes, bays) independently of baseline.
    2. Anomaly: fraction where water_frac > max(median + mad_k × MAD, min_anomaly).
       Adaptive to the orbit's own baseline -- detects spikes at dry sites
       (e.g. 0.3% baseline → two scenes at 15% flagged) without triggering on
       instrument noise or coastal backscatter roughness. The min_anomaly floor
       prevents statistical leakage: MAD is extremely small for stable baselines,
       so even tiny noise excursions would exceed median + k*MAD without the floor.
       MAD itself is robust to flood outliers (not inflated by the anomalies it detects,
       unlike std which is inflated by the very events we want to find).
    """
    n = len(fracs)
    absolute_freq = sum(1 for f in fracs if f > threshold) / n
    loc_median = median(fracs)
    mad_val = _mad(fracs, loc_median)
    adaptive_threshold = max(loc_median + mad_k * mad_val, min_anomaly)
    anomaly_freq = sum(1 for f in fracs if f > adaptive_threshold) / n
    return max(absolute_freq, anomaly_freq)


def compute_sar_water_frequency(
    fracs_with_orbit: list[tuple[float, int]],
    threshold: float = settings.SAR_MIN_WATER_PIXEL_FRACTION,
    mad_k: float = settings.SAR_FLOOD_MAD_K,
    min_anomaly: float = settings.SAR_MIN_ANOMALY_FRACTION,
) -> float | None:
    """Orbit-stratified, MAD-based SAR water frequency.

    Sentinel-1 VV backscatter depends strongly on incidence angle and look
    direction, which differ between orbital passes covering the same location.
    Mixing passes inflates variance and distorts anomaly detection.  Scenes are
    stratified by relative orbit; frequency is computed per track then the max
    across tracks is returned.

    Within each track, two thresholds are evaluated and the higher frequency kept:
    1. Absolute: scenes where water_frac > threshold (default 35%).
    2. Anomaly: scenes where water_frac > max(median + mad_k × MAD, min_anomaly).
       MAD = median(|xi - median(x)|) is robust to the flood outliers it detects.
       The min_anomaly floor prevents false positives from instrument noise at
       tight low-baseline orbits where MAD is near zero.

    Args:
        fracs_with_orbit: list of (water_frac, rel_orbit) tuples after snow masking.
        threshold:        absolute water pixel fraction for chronic flooding (default 35%).
        mad_k:            MAD multiplier for the anomaly threshold (default 2.0).
        min_anomaly:      floor on the anomaly threshold (default 5%).

    Returns None for empty input.
    """
    if not fracs_with_orbit:
        return None

    by_orbit: dict[int, list[float]] = defaultdict(list)
    for wf, orbit in fracs_with_orbit:
        by_orbit[orbit].append(wf)

    orbit_freqs = [
        _orbit_water_frequency(fracs, threshold, mad_k, min_anomaly)
        for fracs in by_orbit.values()
    ]
    return float(max(orbit_freqs))


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
