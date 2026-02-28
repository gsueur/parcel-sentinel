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


def _months_apart(mk1: str, mk2: str) -> int:
    """Return the absolute number of calendar months between two YYYY-MM keys."""
    y1, m1 = int(mk1[:4]), int(mk1[5:7])
    y2, m2 = int(mk2[:4]), int(mk2[5:7])
    return abs((y2 * 12 + m2) - (y1 * 12 + m1))


def _qualify_consecutive(
    month_keys: list[str],
    elevated: list[bool],
    min_run: int,
) -> list[bool]:
    """Keep elevated flags only for positions in calendar-consecutive runs of >= min_run.

    Two adjacent positions are calendar-consecutive if their month keys are
    exactly 1 month apart (handles year boundaries correctly).
    """
    result = [False] * len(elevated)
    i = 0
    while i < len(elevated):
        if not elevated[i]:
            i += 1
            continue
        run = [i]
        j = i + 1
        while j < len(elevated) and elevated[j] and _months_apart(month_keys[j - 1], month_keys[j]) == 1:
            run.append(j)
            j += 1
        if len(run) >= min_run:
            for k in run:
                result[k] = True
        i = j if j > i else i + 1
    return result


def _orbit_water_frequency(
    scenes: list[tuple[str, float]],
    threshold: float,
    mad_k: float,
    min_anomaly: float,
    min_consecutive: int = 1,
) -> float:
    """Compute water frequency for a single orbital pass.

    Two thresholds evaluated; higher frequency returned:
    1. Absolute: fraction of scenes where water_frac > threshold.
       Catches chronically wet locations (lakes, bays). No consecutive
       requirement -- permanent water bodies are real by definition.
    2. Anomaly: fraction where water_frac > max(median + mad_k × MAD, min_anomaly).
       Adaptive to the orbit's own baseline. When min_consecutive > 1, only
       counts anomalous scenes that belong to a calendar-consecutive run of at
       least that length -- eliminates single-scene noise (wind roughening,
       instrument artefacts) while preserving genuine multi-pass flood events.
    """
    scenes_sorted = sorted(scenes, key=lambda x: x[0])
    month_keys = [mk for mk, _ in scenes_sorted]
    fracs = [f for _, f in scenes_sorted]
    n = len(fracs)

    absolute_freq = sum(1 for f in fracs if f > threshold) / n

    loc_median = median(fracs)
    mad_val = _mad(fracs, loc_median)
    adaptive_threshold = max(loc_median + mad_k * mad_val, min_anomaly)
    elevated = [f > adaptive_threshold for f in fracs]
    if min_consecutive > 1:
        elevated = _qualify_consecutive(month_keys, elevated, min_consecutive)
    anomaly_freq = sum(elevated) / n

    return max(absolute_freq, anomaly_freq)


def compute_sar_water_frequency(
    scenes: list[tuple[str, float, int]],
    threshold: float = settings.SAR_MIN_WATER_PIXEL_FRACTION,
    mad_k: float = settings.SAR_FLOOD_MAD_K,
    min_anomaly: float = settings.SAR_MIN_ANOMALY_FRACTION,
    min_consecutive: int = settings.SAR_MIN_CONSECUTIVE_FLOOD_MONTHS,
) -> float | None:
    """Orbit-stratified, MAD-based SAR chronic water frequency.

    Sentinel-1 VV backscatter depends strongly on incidence angle and look
    direction, which differ between orbital passes covering the same location.
    Mixing passes inflates variance and distorts anomaly detection. Scenes are
    stratified by relative orbit; frequency is computed per track then the max
    across tracks is returned.

    Within each track:
    1. Absolute threshold catches chronically wet sites (lakes, bays).
    2. Anomaly threshold (MAD-based) detects recurring flood events relative to
       the orbit's own baseline. Requires min_consecutive calendar-consecutive
       anomalous months to suppress single-pass noise.

    Args:
        scenes:          list of (month_key, water_frac, rel_orbit) after snow/burn masking.
        threshold:       absolute water pixel fraction for chronic flooding (default 35%).
        mad_k:           MAD multiplier for the anomaly threshold (default 2.0).
        min_anomaly:     floor on the anomaly threshold (default 5%).
        min_consecutive: minimum calendar-consecutive anomalous months to count (default 2).

    Returns None for empty input.
    """
    if not scenes:
        return None

    by_orbit: dict[int, list[tuple[str, float]]] = defaultdict(list)
    for mk, wf, orbit in scenes:
        by_orbit[orbit].append((mk, wf))

    orbit_freqs = [
        _orbit_water_frequency(orbit_scenes, threshold, mad_k, min_anomaly, min_consecutive)
        for orbit_scenes in by_orbit.values()
    ]
    return float(max(orbit_freqs))


def compute_sar_flood_anomaly(
    scene_fracs: list[tuple[str, float, int]],
    date_end: str,
    recent_months: int = 2,
    min_baseline_count: int = 2,
) -> float | None:
    """Anomaly-based flood detection: compare recent water_frac to orbit+season baseline.

    Uses ALL scene fracs (no snow suppression) to avoid excluding flood months that
    happen to trigger the S2 NDSI snow filter (flooded fields and snow look similar
    in optical). Each recent scene is compared to the historical median for the same
    (relative orbit, calendar month) combination -- orbit-stratified to avoid mixing
    look angles that produce different baseline backscatter levels.

    Args:
        scene_fracs:       list of (month_key "YYYY-MM", water_frac, rel_orbit).
        date_end:          end of the analysis window "YYYY-MM-DD".
        recent_months:     how many of the most recent calendar months count as "recent".
        min_baseline_count: minimum historical scenes per (orbit, cal_month) for a
                           valid baseline. Falls back to orbit-only baseline if
                           insufficient orbit+month data.

    Returns:
        Peak anomaly (max water_frac - seasonal_orbit_median) in recent window,
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

    # Build orbit-stratified historical baseline keyed by (rel_orbit, cal_month)
    # Fall-back key (0, cal_month) aggregates all orbits for sparse-data locations.
    historical: defaultdict[tuple[int, int], list[float]] = defaultdict(list)
    recent_triples: list[tuple[int, int, float]] = []  # (rel_orbit, cal_month, wf)

    for month_key, wf, orbit in scene_fracs:
        cal_month = int(month_key[5:7])
        if month_key in recent_month_keys:
            recent_triples.append((orbit, cal_month, wf))
        else:
            historical[(orbit, cal_month)].append(wf)
            historical[(0, cal_month)].append(wf)  # orbit-agnostic fallback

    if not recent_triples:
        return None

    anomalies: list[float] = []
    for orbit, cal_month, wf in recent_triples:
        hist = historical.get((orbit, cal_month), [])
        if len(hist) < min_baseline_count:
            hist = historical.get((0, cal_month), [])  # fallback: all orbits
        if len(hist) >= min_baseline_count:
            baseline = median(hist)
            anomalies.append(max(0.0, wf - baseline))

    if not anomalies:
        return None

    return round(min(max(anomalies), 1.0), 4)
