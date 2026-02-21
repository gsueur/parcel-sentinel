from __future__ import annotations

import pytest
from shapely.geometry import Point, Polygon

from src.parcel_sentinel.geometry.normalize import geometry_hash, geojson_to_shapely, round_coordinates
from src.parcel_sentinel.geometry.reproject import area_in_sqm, buffer_in_meters, get_utm_crs
from src.parcel_sentinel.geometry.validate import GeometryValidationError, validate_geometry


class TestNormalize:
    def test_hash_deterministic(self, sample_polygon):
        h1 = geometry_hash(sample_polygon)
        h2 = geometry_hash(sample_polygon)
        assert h1 == h2
        assert len(h1) == 6

    def test_hash_includes_buffers(self, sample_polygon):
        h_no_buf = geometry_hash(sample_polygon)
        h_buf = geometry_hash(sample_polygon, buffers_m=[50, 200])
        assert h_no_buf != h_buf

    def test_hash_different_geom(self, sample_polygon):
        other = Polygon([
            [-77.0, 38.9], [-76.99, 38.9], [-76.99, 38.89], [-77.0, 38.89], [-77.0, 38.9]
        ])
        h1 = geometry_hash(sample_polygon)
        h2 = geometry_hash(other)
        assert h1 != h2

    def test_round_coordinates(self, sample_polygon):
        rounded = round_coordinates(sample_polygon, precision=5)
        assert rounded.is_valid

    def test_geojson_to_shapely(self, sample_geojson):
        geom = geojson_to_shapely(sample_geojson)
        assert geom.geom_type == "Polygon"
        assert not geom.is_empty


class TestReproject:
    def test_get_utm_crs(self):
        crs = get_utm_crs(-77.0, 38.9)
        assert crs.to_epsg() == 32618  # UTM zone 18N

    def test_buffer_in_meters(self, sample_polygon):
        buffered = buffer_in_meters(sample_polygon, 100.0)
        assert buffered.area > sample_polygon.area
        assert buffered.geom_type in ("Polygon", "MultiPolygon")

    def test_buffer_roundtrip(self):
        pt = Point(-77.0, 38.9)
        buffered = buffer_in_meters(pt, 50.0)
        area = area_in_sqm(buffered)
        # Circle of 50m radius should be ~7854 sqm
        assert 7000 < area < 8500

    def test_area_in_sqm(self, sample_polygon):
        area = area_in_sqm(sample_polygon)
        # ~100m x ~110m parcel ~ 11000 sqm
        assert 5000 < area < 200_000


class TestValidate:
    def test_valid_polygon(self, sample_polygon):
        result = validate_geometry(sample_polygon)
        assert result.geom_type in ("Polygon", "MultiPolygon")

    def test_point_gets_buffered(self):
        pt = Point(-77.0, 38.9)
        result = validate_geometry(pt)
        assert result.geom_type == "Polygon"

    def test_empty_geometry_rejected(self):
        from shapely import wkt
        empty = wkt.loads("GEOMETRYCOLLECTION EMPTY")
        with pytest.raises(GeometryValidationError, match="empty"):
            validate_geometry(empty)

    def test_too_large_area_rejected(self, sample_polygon):
        # Use a tiny max area to trigger rejection
        with pytest.raises(GeometryValidationError, match="exceeds limit"):
            validate_geometry(sample_polygon, max_area_sqm=1.0)
