from __future__ import annotations

import numpy as np


def compute_ndvi(nir: np.ndarray, red: np.ndarray) -> np.ndarray:
    """NDVI = (NIR - RED) / (NIR + RED). NaN-safe."""
    with np.errstate(divide="ignore", invalid="ignore"):
        ndvi = (nir - red) / (nir + red)
    return ndvi


def compute_ndwi(green: np.ndarray, nir: np.ndarray) -> np.ndarray:
    """NDWI (McFeeters 1996) = (GREEN - NIR) / (GREEN + NIR). NaN-safe.

    Sentinel-2 bands: B03 (Green) and B08 (NIR).
    Positive values indicate open water; negative values indicate soil and vegetation.
    Locked in processing version s2l2a-v1.1.0.
    """
    with np.errstate(divide="ignore", invalid="ignore"):
        ndwi = (green - nir) / (green + nir)
    return ndwi


def spatial_mean(arr: np.ndarray) -> float | None:
    """Mean of array ignoring NaN. Returns None if all NaN."""
    result = np.nanmean(arr)
    if np.isnan(result):
        return None
    return float(result)
