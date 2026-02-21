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


def compute_ndmi(nir: np.ndarray, swir: np.ndarray) -> np.ndarray:
    """NDMI = (NIR - SWIR1) / (NIR + SWIR1). NaN-safe.

    Sentinel-2: (B08 - B11) / (B08 + B11).
    Measures leaf and canopy water content. Positive values indicate good moisture;
    negative values indicate water stress in vegetation.
    """
    with np.errstate(divide="ignore", invalid="ignore"):
        ndmi = (nir - swir) / (nir + swir)
    return ndmi


def compute_nbr(nir: np.ndarray, swir2: np.ndarray) -> np.ndarray:
    """NBR = (NIR - SWIR2) / (NIR + SWIR2). NaN-safe.

    Sentinel-2: (B08 - B12) / (B08 + B12).
    Detects burned areas and quantifies burn severity. Healthy vegetation has high
    positive values; recently burned areas drop sharply toward negative values.
    """
    with np.errstate(divide="ignore", invalid="ignore"):
        nbr = (nir - swir2) / (nir + swir2)
    return nbr


def compute_ndsi(green: np.ndarray, swir: np.ndarray) -> np.ndarray:
    """NDSI = (GREEN - SWIR1) / (GREEN + SWIR1). NaN-safe.

    Sentinel-2: (B03 - B11) / (B03 + B11).
    Snow has high reflectance in visible green and very low reflectance in SWIR.
    NDSI > 0.4 reliably indicates snow cover.
    """
    with np.errstate(divide="ignore", invalid="ignore"):
        ndsi = (green - swir) / (green + swir)
    return ndsi


def compute_bsi(
    swir: np.ndarray,
    red: np.ndarray,
    nir: np.ndarray,
    blue: np.ndarray,
) -> np.ndarray:
    """BSI = (SWIR1 + RED - NIR - BLUE) / (SWIR1 + RED + NIR + BLUE). NaN-safe.

    Sentinel-2: (B11 + B04 - B08 - B02) / (B11 + B04 + B08 + B02).
    Multi-band bare soil index. SWIR and Red highlight soil; NIR and Blue suppress
    vegetation and shadow. Positive values indicate exposed soil; negative values
    indicate vegetation-covered ground.
    """
    with np.errstate(divide="ignore", invalid="ignore"):
        num = swir + red - nir - blue
        den = swir + red + nir + blue
        bsi = np.where(den != 0, num / den, np.nan)
    return bsi


def spatial_mean(arr: np.ndarray) -> float | None:
    """Mean of array ignoring NaN. Returns None if all NaN."""
    result = np.nanmean(arr)
    if np.isnan(result):
        return None
    return float(result)
