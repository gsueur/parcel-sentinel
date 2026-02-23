from __future__ import annotations

from ..config import settings


def detect_urban(features: dict[str, float | None]) -> bool:
    """Detect urban/impervious surface locations using BSI frequency and NDVI proxies.

    Returns True when all three conditions hold:
      - bsi_bare_soil_freq_5y > URBAN_BSI_FREQ_THRESHOLD (50%)
        Fraction of months where BSI > 0 — impervious surfaces have consistently
        positive BSI. Using frequency rather than mean BSI avoids snow-month
        dilution (SCL=11 pixels now included, snow has strongly negative BSI).
      - NDVI mean < URBAN_NDVI_THRESHOLD (low vegetation)
      - canopy proxy < URBAN_CANOPY_THRESHOLD (or absent)

    Missing bsi_freq or NDVI returns False (safe default: assume non-urban).
    """
    bsi_freq = features.get("bsi_bare_soil_freq_5y")
    ndvi = features.get("ndvi_mean_5y")
    canopy = features.get("canopy_proxy")

    if bsi_freq is None or ndvi is None:
        return False

    bsi_flag = bsi_freq > settings.URBAN_BSI_FREQ_THRESHOLD
    ndvi_flag = ndvi < settings.URBAN_NDVI_THRESHOLD
    canopy_flag = (canopy is None) or (canopy < settings.URBAN_CANOPY_THRESHOLD)

    return bsi_flag and ndvi_flag and canopy_flag
