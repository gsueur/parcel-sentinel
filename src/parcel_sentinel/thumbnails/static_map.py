from __future__ import annotations

import io
import logging

from staticmap import StaticMap, Polygon as SMPolygon

from ..config import settings

logger = logging.getLogger(__name__)


def render_parcel_thumbnail(geojson_geometry: dict) -> bytes:
    """Render a PNG thumbnail of the parcel on an OSM basemap.

    Returns PNG image bytes.
    """
    width = settings.THUMBNAIL_WIDTH
    height = settings.THUMBNAIL_HEIGHT

    m = StaticMap(width, height, padding_x=16, padding_y=16)

    coords = _extract_exterior_coords(geojson_geometry)
    outline = SMPolygon(
        coords,
        fill_color="rgba(59, 130, 246, 0.25)",
        outline_color="rgba(59, 130, 246, 0.9)",
        simplify=True,
    )
    m.add_polygon(outline)

    logger.info("Thumbnail render %dx%d fetching OSM tiles", width, height)
    image = m.render()
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


def _extract_exterior_coords(geojson_geometry: dict) -> list[tuple[float, float]]:
    """Extract exterior ring coordinates as [(lon, lat), ...] from GeoJSON."""
    geom_type = geojson_geometry.get("type", "")
    coordinates = geojson_geometry.get("coordinates", [])

    if geom_type == "Polygon":
        return [(c[0], c[1]) for c in coordinates[0]]
    elif geom_type == "MultiPolygon":
        # Use the first polygon
        return [(c[0], c[1]) for c in coordinates[0][0]]
    else:
        raise ValueError(f"Unsupported geometry type for thumbnail: {geom_type}")
