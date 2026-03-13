from __future__ import annotations

from ..config import settings


def detect_urban(features: dict[str, float | None]) -> bool:
    """Detect urban/impervious surface locations.

    Primary path -- Overture Maps building footprints (when available):
      building_fraction > 0.10  → urban   (direct measurement, takes precedence)
      building_fraction < 0.02  → not urban (veto; suppresses BSI spectral paths)
      building_fraction in [0.02, 0.10] → fall through to BSI paths

    Spectral fallback (when building_fraction is None):
      Path 1: BSI_freq > 0.65 AND NDVI > 0.25 AND canopy < 0.45
              Tropical/coastal cities (e.g. Miami) with mixed vegetation + impervious.
      Path 2: BSI_freq > 0.50 AND NDVI < 0.25 AND canopy < 0.25
              Dense temperate urban cores (e.g. Boston, Chicago).

    BSI freq = fraction of months where BSI > 0 (frequency avoids snow-month dilution).
    """
    building_fraction = features.get("building_fraction")

    # Overture path: ground-truth building footprint coverage.
    if building_fraction is not None:
        if building_fraction > settings.URBAN_BUILDING_FRACTION_THRESHOLD:
            return True
        if building_fraction < settings.URBAN_BUILDING_FRACTION_VETO:
            return False
        # Ambiguous band [veto, threshold] -- fall through to spectral paths.

    # Spectral fallback.
    bsi_freq = features.get("bsi_bare_soil_freq_5y")
    ndvi = features.get("ndvi_mean_5y")
    canopy = features.get("canopy_proxy")

    if bsi_freq is None:
        return False

    # Guard: very low NDVI indicates naturally barren terrain (desert, alpine rock),
    # not urban impervious. Dense urban cores (e.g. Chicago loop) can reach ~0.08;
    # true desert / alpine rock sits at 0.01-0.04.
    if ndvi is not None and ndvi < settings.URBAN_MIN_NDVI_THRESHOLD:
        return False

    # Path 1: strong BSI + elevated NDVI (tropical/coastal cities, e.g. Miami).
    # Canopy ceiling blocks vineyards and orchards (same spectral signature but
    # canopy > 0.45 from dense seasonal crop cover).
    if (
        bsi_freq > settings.URBAN_BSI_FREQ_STRONG_THRESHOLD
        and ndvi is not None
        and ndvi > settings.URBAN_NDVI_THRESHOLD
        and (canopy is None or canopy < settings.URBAN_BSI_STRONG_MAX_CANOPY)
    ):
        return True

    # Path 2: moderate BSI + low NDVI + low canopy (dense temperate urban cores).
    if ndvi is None:
        return False
    return (
        bsi_freq > settings.URBAN_BSI_FREQ_THRESHOLD
        and ndvi < settings.URBAN_NDVI_THRESHOLD
        and (canopy is None or canopy < settings.URBAN_CANOPY_THRESHOLD)
    )
