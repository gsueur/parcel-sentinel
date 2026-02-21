from __future__ import annotations

import logging

from ..models.common import MapLinks
from .geojson_link import build_geojson_io_url

logger = logging.getLogger(__name__)


def build_map_links(location_key: str, geojson_geometry: dict) -> MapLinks:
    """Build map links for a location response.

    Returns MapLinks with a geojson.io URL and a thumbnail endpoint URL.
    """
    geojson_url = build_geojson_io_url(geojson_geometry)
    thumbnail_url = f"/v1/thumbnail/{location_key}.png"

    return MapLinks(
        geojson_io_url=geojson_url,
        thumbnail_url=thumbnail_url,
    )
