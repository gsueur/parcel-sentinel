from __future__ import annotations

import json
import logging
from urllib.parse import quote

import pyproj
import httpx
from shapely.geometry import box, mapping, shape

from ..config import settings
from ..geometry.reproject import buffer_in_meters, get_utm_crs, reproject_geometry

logger = logging.getLogger(__name__)

_MAPBOX_BASE = "https://api.mapbox.com/styles/v1/{style}/static/{overlay}/{bbox}/{w}x{h}@2x"


def _scene_footprint(geojson_geometry: dict) -> dict:
    """Return the overlay geometry that represents the actual satellite analysis extent.

    For Point inputs: a square of COG_WINDOW_SIZE × pixel_size_m, centered on the
    point in UTM, reprojected to WGS84. This matches the exact 640m × 640m window
    read from the COG.
    For Polygon / MultiPolygon: returned as-is (the full parcel is the analysis area).
    """
    geom = shape(geojson_geometry)
    if geom.geom_type != "Point":
        return mapping(geom)

    # Build the UTM square: half-side = COG_WINDOW_SIZE / 2 * 10m (native pixel size)
    half = settings.COG_WINDOW_SIZE / 2 * 10.0  # metres (10m band pixel size)
    wgs84 = pyproj.CRS.from_epsg(4326)
    utm_crs = get_utm_crs(geom.x, geom.y)
    pt_utm = reproject_geometry(geom, wgs84, utm_crs)
    square_utm = box(pt_utm.x - half, pt_utm.y - half, pt_utm.x + half, pt_utm.y + half)
    square_wgs84 = reproject_geometry(square_utm, utm_crs, wgs84)
    return mapping(square_wgs84)


async def render_location_thumbnail(geojson_geometry: dict) -> bytes:
    """Fetch a Mapbox Static API map tile whose viewport matches the satellite analysis area.

    Overlays the exact COG footprint (640m × 640m square for point inputs, polygon
    outline for parcel inputs) as a stroke-only blue rectangle. Returns PNG bytes.
    """
    if not settings.MAPBOX_TOKEN:
        raise RuntimeError("MAPBOX_TOKEN is not configured; cannot render thumbnails")

    footprint_geojson = _scene_footprint(geojson_geometry)

    # Expand viewport with landscape context buffer so the map shows surroundings,
    # while the overlay still marks only the actual analysis extent.
    context_geom = buffer_in_meters(shape(footprint_geojson), settings.THUMBNAIL_CONTEXT_BUFFER_M)
    minx, miny, maxx, maxy = context_geom.bounds
    bbox = f"[{minx},{miny},{maxx},{maxy}]"

    feature = {
        "type": "Feature",
        "properties": {
            "stroke": "#3b82f6",
            "stroke-width": 2,
            "stroke-opacity": 1,
            "fill-opacity": 0,
        },
        "geometry": footprint_geojson,
    }
    encoded = quote(json.dumps(feature, separators=(",", ":")), safe="")
    url = _MAPBOX_BASE.format(
        style=settings.MAPBOX_STYLE,
        overlay=f"geojson({encoded})",
        bbox=bbox,
        w=settings.THUMBNAIL_WIDTH,
        h=settings.THUMBNAIL_HEIGHT,
    )

    logger.info("Mapbox Static fetch style=%s bbox=%s", settings.MAPBOX_STYLE, bbox)
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(url, params={"access_token": settings.MAPBOX_TOKEN})
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
