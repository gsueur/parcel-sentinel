"""Derive long-term climate features from TerraClimate monthly series.

Input:  {variable: {(year, month): value | None}}
Output: flat dict of feature scalars.

All features are named following the convention used for S2 features (e.g.
tmax_mean_5y, pdsi_drought_freq_5y).  Missing values (None) are excluded from
all calculations -- a feature is set to None only when no valid observations
exist.
"""
from __future__ import annotations

import statistics
from datetime import date

import numpy as np

from ..config import settings


def _valid_values(series: dict[tuple[int, int], float | None]) -> list[float]:
    """Extract non-None values from a {(year, month): value} dict."""
    return [v for v in series.values() if v is not None]


def _theil_sen_slope_per_year(
    monthly_series: dict[tuple[int, int], float | None],
) -> float | None:
    """Compute Theil-Sen robust slope in units-per-year from monthly data.

    Uses the month index (0, 1, ..., N-1) as x-axis and multiplies the
    per-month slope by 12 to convert to per-year.
    """
    points = sorted(
        (y * 12 + (m - 1), v)
        for (y, m), v in monthly_series.items()
        if v is not None
    )
    if len(points) < 4:
        return None
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    try:
        from scipy.stats import theilslopes
        result = theilslopes(ys, xs)
        return float(result.slope) * 12  # convert per-month → per-year
    except Exception:
        return None


def _monthly_climatology(
    monthly_series: dict[tuple[int, int], float | None],
) -> dict[int, tuple[float, float]]:
    """Compute mean and std per calendar month (1–12) from multi-year data.

    Returns {month: (mean, std)}.  Months with fewer than 2 valid observations
    are excluded.
    """
    by_month: dict[int, list[float]] = {}
    for (_, m), v in monthly_series.items():
        if v is not None:
            by_month.setdefault(m, []).append(v)
    result = {}
    for m, vals in by_month.items():
        if len(vals) >= 2:
            result[m] = (statistics.mean(vals), statistics.stdev(vals))
        elif vals:
            result[m] = (vals[0], 0.0)
    return result


def compute_climate_features(
    monthly_series: dict[str, dict[tuple[int, int], float | None]],
    date_start: str,
    date_end: str,
    growing_season_months: list[int],
) -> dict[str, float | None]:
    """Derive scalar features from TerraClimate monthly series.

    Parameters
    ----------
    monthly_series:
        {variable: {(year, month): value}} -- values in real physical units.
    date_start, date_end:
        ISO date strings defining the analysis window (unused directly; years
        are already filtered in the pipeline, kept for future use).
    growing_season_months:
        List of 1-based month numbers defining the growing season (e.g. [5..9]).

    Returns
    -------
    Flat dict with all tmax_*, tmin_*, ppt_*, vpd_*, pdsi_* features.
    All values are float or None if insufficient data.
    """
    features: dict[str, float | None] = {}
    gs_set = set(growing_season_months)

    # ── tmax ──────────────────────────────────────────────────────────────────
    tmax = monthly_series.get("tmax", {})
    tmax_vals = _valid_values(tmax)

    if tmax_vals:
        features["tmax_mean_5y"] = round(statistics.mean(tmax_vals), 2)
        summer_vals = [v for (_, m), v in tmax.items() if m in gs_set and v is not None]
        features["tmax_summer_mean_5y"] = round(statistics.mean(summer_vals), 2) if summer_vals else None

        # Anomaly frequency: fraction of months where tmax > monthly_mean + σ
        clim = _monthly_climatology(tmax)
        anomaly_count = 0
        total_obs = 0
        for (_, m), v in tmax.items():
            if v is None or m not in clim:
                continue
            mean_m, std_m = clim[m]
            sigma = settings.TERRACLIMATE_TMAX_ANOMALY_SIGMA
            total_obs += 1
            if v > mean_m + sigma * std_m:
                anomaly_count += 1
        features["tmax_anomaly_freq_5y"] = (
            round(anomaly_count / total_obs, 4) if total_obs >= 6 else None
        )

        features["tmax_trend_slope_5y"] = (
            round(_theil_sen_slope_per_year(tmax), 4) if len(tmax_vals) >= 12 else None
        )
    else:
        features.update({
            "tmax_mean_5y": None,
            "tmax_summer_mean_5y": None,
            "tmax_anomaly_freq_5y": None,
            "tmax_trend_slope_5y": None,
        })

    # ── tmin ──────────────────────────────────────────────────────────────────
    tmin = monthly_series.get("tmin", {})
    tmin_vals = _valid_values(tmin)
    features["tmin_mean_5y"] = round(statistics.mean(tmin_vals), 2) if tmin_vals else None

    # ── ppt (precipitation) ───────────────────────────────────────────────────
    ppt = monthly_series.get("ppt", {})
    ppt_vals = _valid_values(ppt)
    if ppt_vals:
        # Group by year, sum monthly totals, then take mean of annual sums.
        by_year: dict[int, list[float]] = {}
        for (y, _), v in ppt.items():
            if v is not None:
                by_year.setdefault(y, []).append(v)
        annual_totals = [sum(months) for months in by_year.values() if len(months) >= 10]
        features["ppt_annual_mean_5y"] = (
            round(statistics.mean(annual_totals), 1) if annual_totals else None
        )
    else:
        features["ppt_annual_mean_5y"] = None

    # ── vpd (vapor pressure deficit) ─────────────────────────────────────────
    vpd = monthly_series.get("vpd", {})
    vpd_vals = _valid_values(vpd)
    if vpd_vals:
        features["vpd_mean_5y"] = round(statistics.mean(vpd_vals), 3)
        threshold = settings.TERRACLIMATE_VPD_HIGH_THRESHOLD
        high_count = sum(1 for v in vpd_vals if v > threshold)
        features["vpd_high_freq_5y"] = round(high_count / len(vpd_vals), 4)
    else:
        features["vpd_mean_5y"] = None
        features["vpd_high_freq_5y"] = None

    # ── PDSI (Palmer Drought Severity Index) ─────────────────────────────────
    pdsi = monthly_series.get("PDSI", {})
    pdsi_vals = _valid_values(pdsi)
    if pdsi_vals:
        features["pdsi_mean_5y"] = round(statistics.mean(pdsi_vals), 3)
        threshold = settings.TERRACLIMATE_PDSI_DROUGHT_THRESHOLD
        drought_count = sum(1 for v in pdsi_vals if v < threshold)
        features["pdsi_drought_freq_5y"] = round(drought_count / len(pdsi_vals), 4)
    else:
        features["pdsi_mean_5y"] = None
        features["pdsi_drought_freq_5y"] = None

    return features
