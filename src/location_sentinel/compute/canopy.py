from __future__ import annotations

import logging
from collections import defaultdict

import numpy as np
import shapely

from ..compute.aggregation import MonthlyRecord
from ..config import settings

logger = logging.getLogger(__name__)


def get_growing_season_months(
    latitude: float,
    climate_code: str | None = None,
) -> list[int]:
    """Return growing season months for the given location.

    Accounts for southern hemisphere season inversion and Köppen climate zone:
    - Tropical (A) / Arid (B): full year -- no predictable peak season
    - Mediterranean (Cs): spring window before summer drought
      NH: Mar-Jun  |  SH: Sep-Dec
    - Polar / Alpine (E): short summer peak
      NH: Jun-Aug  |  SH: Dec-Feb
    - Temperate / Continental (C non-Cs, D): canonical summer
      NH: May-Sep (>= 33°) or Mar-Nov (< 33°)  |  SH: mirrored by +6 months
    """
    is_southern = latitude < 0
    code = (climate_code or "").upper()

    # Tropical and Arid: no fixed growing season
    if code.startswith("A") or code.startswith("B"):
        return list(range(1, 13))

    # Mediterranean: peak is spring, before summer drought sets in
    if code.startswith("CS"):
        nh_months = [3, 4, 5, 6]

    # Polar / Alpine: very short summer window
    elif code.startswith("E"):
        nh_months = [6, 7, 8]

    # Temperate, Continental, and unknown: latitude-based summer window
    elif abs(latitude) >= settings.GROWING_SEASON_LAT_THRESHOLD:
        nh_months = list(settings.TEMPERATE_SEASON_MONTHS)
    else:
        nh_months = list(settings.SUBTROPICAL_SEASON_MONTHS)

    if not is_southern:
        return nh_months

    # Southern hemisphere: shift all months by 6 to invert seasons
    # e.g. [5,6,7,8,9] (NH May-Sep) → [11,12,1,2,3] (SH Nov-Mar)
    return [(m + 5) % 12 + 1 for m in nh_months]


def compute_canopy_proxy_from_series(
    ndvi_records: list[MonthlyRecord],
    latitude: float,
    climate_code: str | None = None,
) -> float | None:
    """Compute canopy proxy: mean of peak-season NDVI per year.

    For each year, find the maximum monthly NDVI during the growing season,
    then average across years.
    """
    season_months = get_growing_season_months(latitude, climate_code)

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
