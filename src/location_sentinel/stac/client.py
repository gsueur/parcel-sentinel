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


@dataclass
class SceneRef:
    """Reference to a selected STAC item with metadata."""
    item: pystac.Item
    cloud_cover: float
    month_key: str  # "YYYY-MM"
    overlap_fraction: float = 1.0


@dataclass
class STACSearchResult:
    scenes: list[SceneRef] = field(default_factory=list)
    total_items_found: int = 0
    months_covered: int = 0


def search_scenes(
    geom: shapely.Geometry,
    date_start: str,
    date_end: str,
    max_scenes_per_month: int = settings.MAX_SCENES_PER_MONTH,
    max_total_scenes: int = settings.MAX_TOTAL_SCENES,
    stac_endpoint: str | None = None,
    collection: str = settings.STAC_COLLECTION,
) -> STACSearchResult:
    """Search STAC for Sentinel-2 L2A scenes intersecting geometry.

    Groups by month, picks lowest cloud cover, enforces caps.
    """
    endpoint = stac_endpoint or settings.STAC_ENDPOINTS.split(",")[0].strip()

    logger.info("STAC connect endpoint=%s collection=%s", endpoint, collection)
    catalog = Client.open(endpoint)

    geojson = shapely_to_geojson(geom)
    bbox = list(geom.bounds)  # (minx, miny, maxx, maxy)

    logger.info(
        "STAC search bbox=%s datetime=%s/%s max_items=%d",
        bbox, date_start, date_end, settings.STAC_MAX_ITEMS,
    )
    search = catalog.search(
        collections=[collection],
        intersects=geojson,
        datetime=f"{date_start}/{date_end}",
        max_items=settings.STAC_MAX_ITEMS,
        query={"eo:cloud_cover": {"lt": 80}},
    )

    items = list(search.items())
    logger.info("STAC search returned %d items for bbox=%s", len(items), bbox)

    # Group by month
    by_month: dict[str, list[pystac.Item]] = defaultdict(list)
    for item in items:
        dt = item.datetime or item.properties.get("datetime")
        if isinstance(dt, str):
            dt = datetime.fromisoformat(dt.replace("Z", "+00:00"))
        if dt is None:
            continue
        month_key = dt.strftime("%Y-%m")
        by_month[month_key].append(item)

    # Select best scenes per month
    selected: list[SceneRef] = []
    for month_key in sorted(by_month.keys()):
        month_items = by_month[month_key]
        # Sort by cloud cover (lowest first)
        month_items.sort(
            key=lambda it: it.properties.get("eo:cloud_cover", 100.0)
        )
        for item in month_items[:max_scenes_per_month]:
            if len(selected) >= max_total_scenes:
                break
            cloud = item.properties.get("eo:cloud_cover", 100.0)
            selected.append(SceneRef(
                item=item,
                cloud_cover=cloud,
                month_key=month_key,
            ))
        if len(selected) >= max_total_scenes:
            break

    months_covered = len({s.month_key for s in selected})
    logger.info(
        "Selected %d scenes across %d months", len(selected), months_covered
    )

    return STACSearchResult(
        scenes=selected,
        total_items_found=len(items),
        months_covered=months_covered,
    )
