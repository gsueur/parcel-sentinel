from __future__ import annotations

import hashlib

import shapely
from shapely.geometry import mapping, shape

from ..config import settings


def round_coordinates(geom: shapely.Geometry, precision: int = settings.COORD_PRECISION) -> shapely.Geometry:
    """Round all coordinates to given decimal precision."""
    return shapely.set_precision(geom, 10 ** (-precision))


def geometry_hash(geom: shapely.Geometry, buffers_m: list[int] | None = None) -> str:
    """Deterministic sha256 hash of geometry + buffer params.

    Returns 6-char hex prefix.
    """
    rounded = round_coordinates(geom)
    wkb = rounded.wkb
    h = hashlib.sha256(wkb)
    if buffers_m:
        h.update(",".join(str(b) for b in sorted(buffers_m)).encode())
    return h.hexdigest()[:6]


def make_location_key(
    name: str | None,
    centroid: tuple[float, float],
    customer_id: str | None = None,
) -> str:
    """Stable 6-char key derived from semantic attributes.

    Uses (customer_id, name, centroid rounded to 5 dp) so that the same
    location always gets the same key regardless of whether it was submitted
    as a Point or Polygon, or with minor coordinate variations.

    Centroid precision: 5 decimal places ≈ 1 m -- fine for parcel-level work.
    """
    lon, lat = centroid
    key_str = "|".join([
        (customer_id or "").strip().lower(),
        (name or "").strip().lower(),
        f"{lat:.5f}",
        f"{lon:.5f}",
    ])
    return hashlib.sha256(key_str.encode()).hexdigest()[:6]


def geojson_to_shapely(geojson: dict) -> shapely.Geometry:
    """Convert GeoJSON dict to shapely geometry."""
    return shape(geojson)


def shapely_to_geojson(geom: shapely.Geometry) -> dict:
    """Convert shapely geometry to GeoJSON dict."""
    return mapping(geom)
