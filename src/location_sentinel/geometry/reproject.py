from __future__ import annotations

import math

import pyproj
import shapely
from shapely.ops import transform


def get_utm_crs(lon: float, lat: float) -> pyproj.CRS:
    """Derive UTM CRS from a lon/lat centroid."""
    zone_number = int((lon + 180) / 6) + 1
    hemisphere = "north" if lat >= 0 else "south"
    epsg = 32600 + zone_number if hemisphere == "north" else 32700 + zone_number
    return pyproj.CRS.from_epsg(epsg)


def reproject_geometry(geom: shapely.Geometry, from_crs: pyproj.CRS, to_crs: pyproj.CRS) -> shapely.Geometry:
    """Reproject a shapely geometry between CRS."""
    transformer = pyproj.Transformer.from_crs(from_crs, to_crs, always_xy=True)
    return transform(transformer.transform, geom)


def buffer_in_meters(geom: shapely.Geometry, distance_m: float) -> shapely.Geometry:
    """Buffer a WGS84 geometry by distance in meters.

    Reprojects to UTM, buffers, reprojects back to WGS84.
    """
    centroid = geom.centroid
    utm_crs = get_utm_crs(centroid.x, centroid.y)
    wgs84 = pyproj.CRS.from_epsg(4326)

    geom_utm = reproject_geometry(geom, wgs84, utm_crs)
    buffered_utm = geom_utm.buffer(distance_m)
    return reproject_geometry(buffered_utm, utm_crs, wgs84)


def area_in_sqm(geom: shapely.Geometry) -> float:
    """Compute area of a WGS84 geometry in square meters using UTM."""
    centroid = geom.centroid
    utm_crs = get_utm_crs(centroid.x, centroid.y)
    wgs84 = pyproj.CRS.from_epsg(4326)
    geom_utm = reproject_geometry(geom, wgs84, utm_crs)
    return geom_utm.area
