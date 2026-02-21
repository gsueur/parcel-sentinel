from __future__ import annotations

import shapely
from shapely.validation import make_valid

from ..config import settings
from .reproject import area_in_sqm, buffer_in_meters


class GeometryValidationError(ValueError):
    pass


def validate_geometry(
    geom: shapely.Geometry,
    max_area_sqm: float = settings.MAX_PARCEL_AREA_SQM,
    max_vertices: int = settings.MAX_VERTICES,
) -> shapely.Geometry:
    """Validate and optionally fix a geometry.

    - Makes geometry valid if needed
    - Checks area limit
    - Simplifies if vertex count exceeds threshold
    - Converts Point to buffered polygon

    Returns validated geometry (always a Polygon/MultiPolygon in WGS84).
    """
    if geom.is_empty:
        raise GeometryValidationError("Geometry is empty")

    # Handle Point: buffer to polygon
    if geom.geom_type == "Point":
        geom = buffer_in_meters(geom, settings.DEFAULT_POINT_BUFFER_M)

    # Make valid
    if not geom.is_valid:
        geom = make_valid(geom)

    # Check area
    area = area_in_sqm(geom)
    if area > max_area_sqm:
        raise GeometryValidationError(
            f"Geometry area {area:.0f} sqm exceeds limit {max_area_sqm:.0f} sqm"
        )

    # Simplify if too many vertices
    num_coords = sum(len(ring.coords) for ring in _all_rings(geom))
    if num_coords > max_vertices:
        geom = geom.simplify(0.0001, preserve_topology=True)

    return geom


def _all_rings(geom: shapely.Geometry):
    """Yield all linear rings from a Polygon or MultiPolygon."""
    if geom.geom_type == "Polygon":
        yield geom.exterior
        yield from geom.interiors
    elif geom.geom_type == "MultiPolygon":
        for poly in geom.geoms:
            yield poly.exterior
            yield from poly.interiors
