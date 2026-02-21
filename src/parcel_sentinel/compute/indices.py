from __future__ import annotations

import numpy as np


def compute_ndvi(nir: np.ndarray, red: np.ndarray) -> np.ndarray:
    """NDVI = (NIR - RED) / (NIR + RED). NaN-safe."""
    with np.errstate(divide="ignore", invalid="ignore"):
        ndvi = (nir - red) / (nir + red)
    return ndvi


def compute_ndwi_gao(nir: np.ndarray, swir: np.ndarray) -> np.ndarray:
    """NDWI (Gao) = (NIR - SWIR) / (NIR + SWIR). NaN-safe.

    Uses the Gao (1996) moisture index definition locked in processing version s2l2a-v1.0.0.
    """
    with np.errstate(divide="ignore", invalid="ignore"):
        ndwi = (nir - swir) / (nir + swir)
    return ndwi


def spatial_mean(arr: np.ndarray) -> float | None:
    """Mean of array ignoring NaN. Returns None if all NaN."""
    result = np.nanmean(arr)
    if np.isnan(result):
        return None
    return float(result)
