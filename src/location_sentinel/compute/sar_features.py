from __future__ import annotations

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
) -> float | None:
    """Fraction of scenes exceeding the water pixel fraction threshold.

    Returns None for empty input.
    """
    if not water_fracs:
        return None
    flooded = sum(1 for f in water_fracs if f > threshold)
    return float(flooded) / len(water_fracs)
