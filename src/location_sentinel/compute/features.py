from __future__ import annotations

import numpy as np
from scipy.stats import theilslopes

from ..compute.aggregation import MonthlyRecord
from ..config import settings


def compute_trend_slope(records: list[MonthlyRecord]) -> float | None:
    """Compute Theil-Sen trend slope from monthly records.

    Returns slope in index units per year. None if insufficient data.
    """
    valid = [(i, r.mean) for i, r in enumerate(records) if r.mean is not None]
    if len(valid) < 6:
        return None

    x = np.array([v[0] for v in valid], dtype=np.float64)
    y = np.array([v[1] for v in valid], dtype=np.float64)

    slope, _, _, _ = theilslopes(y, x)
    # Convert from per-month to per-year
    slope_per_year = float(slope) * 12.0
    return round(slope_per_year, 6)


def compute_anomaly_frequency(
    records: list[MonthlyRecord],
    threshold: float = settings.NDVI_ANOMALY_THRESHOLD,
    min_consecutive: int = 1,
) -> float | None:
    """Fraction of observed months where anomaly < -threshold vs monthly climatology.

    When min_consecutive > 1, only months that belong to a run of at least
    that many calendar-consecutive anomaly observations are counted. This
    discriminates persistent disturbances (fire scars, which depress NBR for
    months to years) from transient ones (harvest, single-month drought) that
    produce isolated dips before snow or regrowth resets the signal.

    Returns fraction in [0, 1]. None if insufficient data.
    """
    # Build monthly climatology from all valid records
    by_calendar_month: dict[int, list[float]] = {}
    for rec in records:
        if rec.mean is None:
            continue
        cal_month = int(rec.month.split("-")[1])
        by_calendar_month.setdefault(cal_month, []).append(rec.mean)

    if not by_calendar_month:
        return None

    climatology = {m: np.mean(vals) for m, vals in by_calendar_month.items()}

    # Work on sorted valid records only (chronological order required for run detection)
    sorted_recs = sorted((r for r in records if r.mean is not None), key=lambda r: r.month)
    observed = len(sorted_recs)
    if observed == 0:
        return None

    # Pre-compute per-month anomaly flags
    is_anomaly = []
    for rec in sorted_recs:
        cal_month = int(rec.month.split("-")[1])
        clim = climatology.get(cal_month)
        is_anomaly.append(clim is not None and (rec.mean - clim) < -threshold)

    if min_consecutive <= 1:
        return round(sum(is_anomaly) / observed, 4)

    # Identify qualifying months: those in a run of >= min_consecutive
    # calendar-consecutive anomaly observations. A gap in observations breaks the run.
    def _next_month(m: str) -> str:
        y, mo = int(m[:4]), int(m[5:7])
        mo += 1
        if mo > 12:
            mo, y = 1, y + 1
        return f"{y:04d}-{mo:02d}"

    qualifying = [False] * observed
    i = 0
    while i < observed:
        if not is_anomaly[i]:
            i += 1
            continue
        # Extend run while months are anomalous AND calendar-consecutive
        run_start = i
        j = i + 1
        while (
            j < observed
            and is_anomaly[j]
            and sorted_recs[j].month == _next_month(sorted_recs[j - 1].month)
        ):
            j += 1
        if j - run_start >= min_consecutive:
            for k in range(run_start, j):
                qualifying[k] = True
        i = j

    return round(sum(qualifying) / observed, 4)


def compute_recent_anomaly_ratio(
    records: list[MonthlyRecord],
    date_end: str,
    recent_months: int = 12,
    threshold: float = settings.NDVI_ANOMALY_THRESHOLD,
    direction: str = "below",
) -> float | None:
    """Ratio of recent-window anomaly frequency to 5y baseline frequency.

    Compares how often the index was anomalous in the last `recent_months`
    relative to the full series. A ratio > 1 means conditions are worsening;
    < 1 means improving. Capped at 5.0 to bound the amplifier.

    direction: 'below' -- anomaly when value < climatology - threshold (NDVI, NDMI)
               'above' -- anomaly when value > climatology + threshold (future use)

    Returns None if baseline frequency is near zero (no historical anomalies to
    compare against) or if the recent window has fewer than 3 observations.
    """
    sorted_recs = sorted((r for r in records if r.mean is not None), key=lambda r: r.month)
    if len(sorted_recs) < 6:
        return None

    by_calendar_month: dict[int, list[float]] = {}
    for rec in sorted_recs:
        cal_month = int(rec.month.split("-")[1])
        by_calendar_month.setdefault(cal_month, []).append(rec.mean)
    climatology = {m: float(np.mean(vals)) for m, vals in by_calendar_month.items()}

    end_year, end_month = int(date_end[:4]), int(date_end[5:7])
    end_abs = end_year * 12 + end_month

    def _is_anomaly(rec: MonthlyRecord) -> bool:
        cal_month = int(rec.month.split("-")[1])
        clim = climatology.get(cal_month)
        if clim is None:
            return False
        if direction == "below":
            return (rec.mean - clim) < -threshold
        return (rec.mean - clim) > threshold

    total = len(sorted_recs)
    baseline_count = sum(1 for r in sorted_recs if _is_anomaly(r))
    baseline_freq = baseline_count / total
    if baseline_freq < 0.01:
        return None

    recent_recs = [
        r for r in sorted_recs
        if 0 <= end_abs - (int(r.month[:4]) * 12 + int(r.month[5:7])) < recent_months
    ]
    if len(recent_recs) < 3:
        return None

    recent_count = sum(1 for r in recent_recs if _is_anomaly(r))
    recent_freq = recent_count / len(recent_recs)

    return round(min(recent_freq / baseline_freq, 5.0), 4)


def compute_wetness_persistence(
    records: list[MonthlyRecord],
    threshold: float = settings.NDWI_WET_THRESHOLD,
) -> float | None:
    """Fraction of months with NDWI above threshold.

    Returns fraction in [0, 1]. None if no data.
    """
    valid = [r for r in records if r.mean is not None]
    if not valid:
        return None

    wet_count = sum(1 for r in valid if r.mean > threshold)
    return round(wet_count / len(valid), 4)


def compute_moisture_stress_frequency(
    records: list[MonthlyRecord],
    threshold: float = settings.NDMI_STRESS_THRESHOLD,
) -> float | None:
    """Fraction of months with NDMI below threshold (vegetation moisture stress).

    Returns fraction in [0, 1]. None if no data.
    """
    valid = [r for r in records if r.mean is not None]
    if not valid:
        return None
    stress_count = sum(1 for r in valid if r.mean < threshold)
    return round(stress_count / len(valid), 4)


def get_persistent_burn_months(
    records: list[MonthlyRecord],
    threshold: float = settings.NBR_ANOMALY_THRESHOLD,
    min_consecutive: int = 2,
) -> set[str]:
    """Return month keys belonging to genuine burn events (anomaly-based).

    Detects months where NBR drops more than `threshold` below the site's own
    seasonal climatology. This is the same criterion used by the fire score and
    correctly handles Mediterranean dry seasons: a naturally low NBR in summer
    (e.g. Cape Town fynbos) has zero anomaly relative to the site climatology
    and is never suppressed, while a genuine fire scar produces an abrupt
    departure well below the seasonal norm.

    Requires at least min_consecutive calendar-consecutive anomaly months to
    filter isolated disturbances (agricultural harvest, single drought months).

    Used for SAR burn suppression and chart annotation.
    """
    sorted_recs = sorted((r for r in records if r.mean is not None), key=lambda r: r.month)
    if not sorted_recs:
        return set()

    # Build seasonal climatology
    by_cal_month: dict[int, list[float]] = {}
    for r in sorted_recs:
        cal_month = int(r.month.split("-")[1])
        by_cal_month.setdefault(cal_month, []).append(r.mean)
    climatology = {m: float(np.mean(vals)) for m, vals in by_cal_month.items()}

    # Anomaly flag: NBR drops more than threshold below the site's seasonal norm
    is_burn = []
    for r in sorted_recs:
        cal_month = int(r.month.split("-")[1])
        clim = climatology.get(cal_month)
        is_burn.append(clim is not None and (r.mean - clim) < -threshold)

    def _next_month(m: str) -> str:
        y, mo = int(m[:4]), int(m[5:7])
        mo += 1
        if mo > 12:
            mo, y = 1, y + 1
        return f"{y:04d}-{mo:02d}"

    burn_months: set[str] = set()
    i = 0
    while i < len(sorted_recs):
        if not is_burn[i]:
            i += 1
            continue
        run_start = i
        j = i + 1
        while (
            j < len(sorted_recs)
            and is_burn[j]
            and sorted_recs[j].month == _next_month(sorted_recs[j - 1].month)
        ):
            j += 1
        if j - run_start >= min_consecutive:
            for k in range(run_start, j):
                burn_months.add(sorted_recs[k].month)
        i = j

    return burn_months


def compute_snow_persistence(
    records: list[MonthlyRecord],
    threshold: float = settings.NDSI_SNOW_THRESHOLD,
) -> float | None:
    """Fraction of months with NDSI above threshold (snow-covered).

    Returns fraction in [0, 1]. None if no data.
    """
    valid = [r for r in records if r.mean is not None]
    if not valid:
        return None
    snow_count = sum(1 for r in valid if r.mean > threshold)
    return round(snow_count / len(valid), 4)


def compute_bare_soil_frequency(
    records: list[MonthlyRecord],
    threshold: float = settings.BSI_BARE_THRESHOLD,
) -> float | None:
    """Fraction of months with BSI above threshold (bare soil exposed).

    Returns fraction in [0, 1]. None if no data.
    """
    valid = [r for r in records if r.mean is not None]
    if not valid:
        return None
    bare_count = sum(1 for r in valid if r.mean > threshold)
    return round(bare_count / len(valid), 4)


def compute_mean(records: list[MonthlyRecord]) -> float | None:
    """Mean of all valid monthly values."""
    valid = [r.mean for r in records if r.mean is not None]
    if not valid:
        return None
    return round(float(np.mean(valid)), 6)


def compute_percentile(records: list[MonthlyRecord], pct: float) -> float | None:
    """Percentile of valid monthly values."""
    valid = [r.mean for r in records if r.mean is not None]
    if not valid:
        return None
    return round(float(np.percentile(valid, pct)), 6)


def compute_quality_score(
    months_total: int,
    months_observed: int,
    mean_cloud_fraction: float,
) -> float:
    """Quality score in [0, 1].

    Weighted sum: 65% temporal coverage + 35% scene clarity.
    mean_cloud_fraction should be computed only over observed months so that
    fully-cloudy months are not double-penalised (they already reduce coverage).
    """
    if months_total == 0:
        return 0.0

    coverage = min(months_observed / months_total, 1.0)
    clarity = 1.0 - mean_cloud_fraction

    return round(0.65 * coverage + 0.35 * clarity, 4)
