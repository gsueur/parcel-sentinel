from __future__ import annotations

from ..config import settings


def detect_urban(features: dict[str, float | None]) -> bool:
    """Detect urban/impervious surface locations using BSI frequency and NDVI proxies.

    Two detection paths (OR logic):
      1. Strong BSI signal alone: bsi_bare_soil_freq_5y > URBAN_BSI_FREQ_STRONG_THRESHOLD (65%)
         Catches tropical/coastal cities (e.g. Miami) where vegetation mixed with
         impervious surfaces keeps NDVI elevated despite dense urbanisation.
      2. Combined signal: BSI freq > 50% AND NDVI < 0.25 AND low/absent canopy
         Standard dense urban pattern (e.g. Boston).

    BSI freq = fraction of months where BSI > 0. Using frequency rather than mean
    BSI avoids snow-month dilution (snow on impervious surfaces has negative BSI).

    Missing bsi_freq returns False (safe default: assume non-urban).
    """
    bsi_freq = features.get("bsi_bare_soil_freq_5y")
    ndvi = features.get("ndvi_mean_5y")
    canopy = features.get("canopy_proxy")

    if bsi_freq is None:
        return False

    # Guard: near-zero 5-year mean NDVI means the site is naturally barren
    # (desert, alpine rock, bare soil), not urban impervious. Every urban
    # environment has enough mixed vegetation (street trees, verges, parks)
    # to keep the 640m window mean above ~0.12. Below that threshold the
    # high BSI frequency reflects an absence of vegetation, not impervious
    # surfaces, and both detection paths must be suppressed.
    if ndvi is not None and ndvi < settings.URBAN_MIN_NDVI_THRESHOLD:
        return False

    # Path 1: overwhelmingly impervious signal with elevated vegetation (tropical/coastal cities,
    # e.g. Miami). Requires ndvi > URBAN_NDVI_THRESHOLD (0.25) because this path was specifically
    # designed for high-vegetation urban mixes -- rocky/arid terrain with high BSI from bare rock
    # but low-medium NDVI would otherwise be mis-classified. Path 2 handles the medium-NDVI case.
    if (
        bsi_freq > settings.URBAN_BSI_FREQ_STRONG_THRESHOLD
        and ndvi is not None
        and ndvi > settings.URBAN_NDVI_THRESHOLD
    ):
        return True

    # Path 2: moderate BSI + low NDVI + low/absent canopy
    if ndvi is None:
        return False
    bsi_flag = bsi_freq > settings.URBAN_BSI_FREQ_THRESHOLD
    ndvi_flag = ndvi < settings.URBAN_NDVI_THRESHOLD
    canopy_flag = (canopy is None) or (canopy < settings.URBAN_CANOPY_THRESHOLD)

    return bsi_flag and ndvi_flag and canopy_flag
