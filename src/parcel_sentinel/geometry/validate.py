from __future__ import annotations

import shapely


class GeometryValidationError(ValueError):
    pass


def validate_geometry(geom: shapely.Geometry) -> shapely.Geometry:
    """Validate that the input is a non-empty Point.

    Only Point geometries are accepted. Polygon inputs are rejected.
    Returns the Point unchanged.
    """
    if geom.is_empty:
        raise GeometryValidationError("Geometry is empty")
    if geom.geom_type != "Point":
        raise GeometryValidationError(
            f"Only Point geometries are supported, got {geom.geom_type}"
        )
    return geom
