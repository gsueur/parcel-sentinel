from __future__ import annotations

import json
import logging
from urllib.parse import quote

import httpx
from shapely.geometry import mapping, shape

from ..config import settings
from ..geometry.reproject import buffer_in_meters

logger = logging.getLogger(__name__)

_MAPBOX_BASE = "https://api.mapbox.com/styles/v1/{style}/static/{overlay}/{bbox}/{w}x{h}@2x"


def _analysis_geometry(geojson_geometry: dict) -> dict:
    """Return the actual analysis boundary as GeoJSON.

    For Point inputs: reprojects to UTM, buffers by DEFAULT_POINT_BUFFER_M,
    reprojects back to WGS84 — exactly matching what the pipeline analyzes.
    For Polygon/MultiPolygon: returned as-is.
    """
    geom = shape(geojson_geometry)
    if geom.geom_type == "Point":
        geom = buffer_in_meters(geom, settings.DEFAULT_POINT_BUFFER_M)
    return mapping(geom)


async def render_parcel_thumbnail(geojson_geometry: dict) -> bytes:
    """Fetch a Mapbox Static API map tile whose viewport matches the satellite analysis area.

    For Point inputs the viewport covers the 100m-buffered circle, matching the
    64×64-pixel COG window actually read. Returns PNG image bytes.
    """
    analysis_geojson = _analysis_geometry(geojson_geometry)

    feature = {
        "type": "Feature",
        "properties": {
            "stroke": "#3b82f6",
            "stroke-width": 2,
            "stroke-opacity": 1,
            "fill": "#3b82f6",
            "fill-opacity": 0.2,
        },
        "geometry": analysis_geojson,
    }
    encoded = quote(json.dumps(feature, separators=(",", ":")), safe="")
    overlay = f"geojson({encoded})"

    # Expand viewport with landscape context buffer so the map shows surroundings,
    # while the GeoJSON overlay still marks only the actual analysis geometry.
    context_geom = buffer_in_meters(shape(analysis_geojson), settings.THUMBNAIL_CONTEXT_BUFFER_M)
    minx, miny, maxx, maxy = context_geom.bounds
    bbox = f"[{minx},{miny},{maxx},{maxy}]"

    url = _MAPBOX_BASE.format(
        style=settings.MAPBOX_STYLE,
        overlay=overlay,
        bbox=bbox,
        w=settings.THUMBNAIL_WIDTH,
        h=settings.THUMBNAIL_HEIGHT,
    )

    logger.info("Mapbox Static fetch style=%s bbox=%s", settings.MAPBOX_STYLE, bbox)
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
