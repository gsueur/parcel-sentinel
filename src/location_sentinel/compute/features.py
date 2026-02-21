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
) -> float | None:
    """Fraction of months where anomaly < -threshold vs monthly climatology.

    Returns fraction in [0, 1]. None if insufficient data.
    """
    # Build monthly climatology
    by_calendar_month: dict[int, list[float]] = {}
    for rec in records:
        if rec.mean is None:
            continue
        cal_month = int(rec.month.split("-")[1])
        by_calendar_month.setdefault(cal_month, []).append(rec.mean)

    if not by_calendar_month:
        return None

    climatology = {m: np.mean(vals) for m, vals in by_calendar_month.items()}

    # Count anomalies
    observed = 0
    anomaly_count = 0
    for rec in records:
        if rec.mean is None:
            continue
        cal_month = int(rec.month.split("-")[1])
        clim = climatology.get(cal_month)
        if clim is None:
            continue
        observed += 1
        if rec.mean - clim < -threshold:
            anomaly_count += 1

    if observed == 0:
        return None

    return round(anomaly_count / observed, 4)


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


def compute_burn_frequency(
    records: list[MonthlyRecord],
    threshold: float = settings.NBR_BURN_THRESHOLD,
) -> float | None:
    """Fraction of months with NBR below threshold (burn signal present).

    Returns fraction in [0, 1]. None if no data.
    """
    valid = [r for r in records if r.mean is not None]
    if not valid:
        return None
    burn_count = sum(1 for r in valid if r.mean < threshold)
    return round(burn_count / len(valid), 4)


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

    quality = coverage_factor * clarity_factor * confidence_factor
    """
    if months_total == 0:
        return 0.0

    coverage = months_observed / months_total
    clarity = 1.0 - mean_cloud_fraction

    # Confidence factor: 1.0 if obs >= 50% of total, linear scale-down otherwise
    if coverage >= 0.5:
        confidence = 1.0
    else:
        confidence = coverage / 0.5

    return round(coverage * clarity * confidence, 4)
