from __future__ import annotations

import json
import logging
from urllib.parse import quote

import httpx

from ..config import settings

logger = logging.getLogger(__name__)

_MAPBOX_BASE = "https://api.mapbox.com/styles/v1/{style}/static/{overlay}/auto/{w}x{h}@2x"


async def render_parcel_thumbnail(geojson_geometry: dict) -> bytes:
    """Fetch a Mapbox Static API map tile with the parcel overlay.

    Returns PNG image bytes.
    """
    feature = {
        "type": "Feature",
        "properties": {
            "stroke": "#3b82f6",
            "stroke-width": 2,
            "stroke-opacity": 1,
            "fill": "#3b82f6",
            "fill-opacity": 0.2,
        },
        "geometry": geojson_geometry,
    }
    encoded = quote(json.dumps(feature, separators=(",", ":")), safe="")
    overlay = f"geojson({encoded})"

    url = _MAPBOX_BASE.format(
        style=settings.MAPBOX_STYLE,
        overlay=overlay,
        w=settings.THUMBNAIL_WIDTH,
        h=settings.THUMBNAIL_HEIGHT,
    )

    logger.info("Mapbox Static fetch style=%s", settings.MAPBOX_STYLE)
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(url, params={"padding": "40", "access_token": settings.MAPBOX_TOKEN})
        resp.raise_for_status()

    return resp.content


def _extract_exterior_coords(geojson_geometry: dict) -> list[tuple[float, float]]:
    """Extract exterior ring coordinates as [(lon, lat), ...] from GeoJSON."""
    geom_type = geojson_geometry.get("type", "")
    coordinates = geojson_geometry.get("coordinates", [])

    if geom_type == "Polygon":
        return [(c[0], c[1]) for c in coordinates[0]]
    elif geom_type == "MultiPolygon":
        return [(c[0], c[1]) for c in coordinates[0][0]]
    else:
        raise ValueError(f"Unsupported geometry type for thumbnail: {geom_type}")
