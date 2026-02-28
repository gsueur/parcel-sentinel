from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime

import pystac
import shapely
from pystac_client import Client

from ..config import settings
from ..geometry.normalize import shapely_to_geojson

logger = logging.getLogger(__name__)


def _relative_orbit(item: pystac.Item) -> int:
    """Extract the relative orbit number from a Sentinel-1 STAC item.

    Tries ``sat:relative_orbit`` property first (present in Earth Search v1).
    Falls back to computing from the absolute orbit in the scene ID:
      - S1A: (abs_orbit - 73) % 175 + 1
      - S1B: (abs_orbit - 26) % 175 + 1
    Returns 0 if the orbit cannot be determined.
    """
    rel = item.properties.get("sat:relative_orbit")
    if rel is not None:
        return int(rel)

    # Derive from absolute orbit
    abs_orbit = item.properties.get("sat:absolute_orbit")
    if abs_orbit is None:
        # Parse from scene ID: S1[AB]_IW_GRDH_1SDV_..._AAAAAA_TTTTTT
        try:
            abs_orbit = int(item.id.split("_")[6])
        except (IndexError, ValueError):
            return 0
    abs_orbit = int(abs_orbit)
    platform = item.properties.get("platform", "sentinel-1a").lower()
    offset = 26 if "1b" in platform else 73
    return (abs_orbit - offset) % 175 + 1


@dataclass
class SARSceneRef:
    """Reference to a selected Sentinel-1 GRD STAC item."""
    item: pystac.Item
    month_key: str   # "YYYY-MM"
    rel_orbit: int   # Sentinel-1 relative orbit number (1-175)


@dataclass
class SARSearchResult:
    scenes: list[SARSceneRef] = field(default_factory=list)
    total_items_found: int = 0
    months_covered: int = 0


def search_sar_scenes(
    geom: shapely.Geometry,
    date_start: str,
    date_end: str,
    max_scenes_per_month: int = settings.SAR_MAX_SCENES_PER_MONTH,
    max_total_scenes: int = settings.SAR_MAX_TOTAL_SCENES,
    stac_endpoint: str | None = None,
) -> SARSearchResult:
    """Search Earth Search v1 for Sentinel-1 GRD IW scenes intersecting geometry.

    Filters to IW mode with a VV asset. Groups by month and selects up to
    max_scenes_per_month per month.  No cloud filter (SAR is cloud-free).
    """
    endpoint = stac_endpoint or settings.STAC_ENDPOINTS.split(",")[0].strip()

    logger.info(
        "S1 STAC connect endpoint=%s collection=%s",
        endpoint, settings.SAR_STAC_COLLECTION,
    )
    catalog = Client.open(endpoint)
    geojson = shapely_to_geojson(geom)

    logger.info(
        "S1 STAC search bbox=%s datetime=%s/%s max_items=%d",
        list(geom.bounds), date_start, date_end, max_total_scenes * 3,
    )
    search = catalog.search(
        collections=[settings.SAR_STAC_COLLECTION],
        intersects=geojson,
        datetime=f"{date_start}/{date_end}",
        max_items=max_total_scenes * 3,
    )

    items = list(search.items())
    logger.info("S1 STAC returned %d raw items", len(items))

    # Filter to IW mode with a VV asset
    iw_items = [
        it for it in items
        if it.properties.get("sar:instrument_mode", "") == "IW"
        and "vv" in it.assets
    ]
    logger.info("S1 IW GRD items with VV asset: %d", len(iw_items))

    # Group by month
    by_month: dict[str, list[pystac.Item]] = defaultdict(list)
    for item in iw_items:
        dt = item.datetime or item.properties.get("datetime")
        if isinstance(dt, str):
            dt = datetime.fromisoformat(dt.replace("Z", "+00:00"))
        if dt is None:
            continue
        month_key = dt.strftime("%Y-%m")
        by_month[month_key].append(item)

    # Select 1 scene per (orbit, month): guarantees orbit diversity without
    # redundant same-orbit scenes. max_scenes_per_month caps the number of
    # distinct orbits kept per month (typically 2-3 for CONUS/Europe).
    selected: list[SARSceneRef] = []
    for month_key in sorted(by_month.keys()):
        if len(selected) >= max_total_scenes:
            break
        # First item seen per orbit is the representative for that pass
        by_orbit: dict[int, pystac.Item] = {}
        for item in by_month[month_key]:
            orbit = _relative_orbit(item)
            if orbit not in by_orbit:
                by_orbit[orbit] = item
        # Keep up to max_scenes_per_month orbits, sorted for determinism
        for orbit, item in sorted(by_orbit.items())[:max_scenes_per_month]:
            if len(selected) >= max_total_scenes:
                break
            selected.append(SARSceneRef(item=item, month_key=month_key, rel_orbit=orbit))

    months_covered = len({s.month_key for s in selected})
    logger.info(
        "S1: selected %d scenes across %d months", len(selected), months_covered,
    )

    return SARSearchResult(
        scenes=selected,
        total_items_found=len(iw_items),
        months_covered=months_covered,
    )
