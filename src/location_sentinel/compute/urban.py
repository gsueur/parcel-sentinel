from __future__ import annotations

from ..config import settings


def detect_urban(features: dict[str, float | None]) -> bool:
    """Detect urban/impervious surface locations using BSI and NDVI proxies.

    Returns True when all three conditions hold:
      - BSI mean > URBAN_BSI_THRESHOLD  (high bare-soil/impervious signal)
      - NDVI mean < URBAN_NDVI_THRESHOLD (low vegetation)
      - canopy proxy < URBAN_CANOPY_THRESHOLD (or absent)

    Missing BSI or NDVI returns False (safe default: assume non-urban).
    """
    bsi = features.get("bsi_mean_5y")
    ndvi = features.get("ndvi_mean_5y")
    canopy = features.get("canopy_proxy_200m") or features.get("canopy_proxy_50m")

    if bsi is None or ndvi is None:
        return False

    bsi_flag = bsi > settings.URBAN_BSI_THRESHOLD
    ndvi_flag = ndvi < settings.URBAN_NDVI_THRESHOLD
    canopy_flag = (canopy is None) or (canopy < settings.URBAN_CANOPY_THRESHOLD)

    return bsi_flag and ndvi_flag and canopy_flag
