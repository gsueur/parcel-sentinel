from __future__ import annotations

import logging
from collections import defaultdict

import numpy as np
import shapely

from ..compute.aggregation import MonthlyRecord
from ..config import settings

logger = logging.getLogger(__name__)


def get_growing_season_months(latitude: float) -> list[int]:
    """Return growing season months based on latitude zone."""
    if latitude >= settings.GROWING_SEASON_LAT_THRESHOLD:
        return settings.TEMPERATE_SEASON_MONTHS
    return settings.SUBTROPICAL_SEASON_MONTHS


def compute_canopy_proxy_from_series(
    ndvi_records: list[MonthlyRecord],
    latitude: float,
) -> float | None:
    """Compute canopy proxy: mean of peak-season NDVI per year.

    For each year, find the maximum monthly NDVI during the growing season,
    then average across years.
    """
    season_months = get_growing_season_months(latitude)

    # Group by year
    by_year: dict[int, list[MonthlyRecord]] = defaultdict(list)
    for rec in ndvi_records:
        if rec.mean is None:
            continue
        year = int(rec.month.split("-")[0])
        cal_month = int(rec.month.split("-")[1])
        if cal_month in season_months:
            by_year[year].append(rec)

    if not by_year:
        return None

    # Peak NDVI per year
    peaks: list[float] = []
    for year in sorted(by_year.keys()):
        year_vals = [r.mean for r in by_year[year] if r.mean is not None]
        if year_vals:
            peaks.append(max(year_vals))

    if not peaks:
        return None

    return round(float(np.mean(peaks)), 6)
