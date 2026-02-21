from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from src.location_sentinel.app import create_app
from src.location_sentinel.thumbnails.geojson_link import build_geojson_io_url
from src.location_sentinel.thumbnails.links import build_map_links

SAMPLE_GEOJSON = {
    "type": "Polygon",
    "coordinates": [[
        [-77.0365, 38.8977],
        [-77.0355, 38.8977],
        [-77.0355, 38.8967],
        [-77.0365, 38.8967],
        [-77.0365, 38.8977],
    ]],
}


class TestGeojsonLink:
    def test_builds_valid_url(self):
        url = build_geojson_io_url(SAMPLE_GEOJSON)
        assert url is not None
        assert url.startswith("https://geojson.io/#data=data:application/json,")
        assert "Polygon" in url

    def test_returns_none_for_huge_geometry(self):
        """Geometry with thousands of vertices should exceed URL limit."""
        huge_coords = [[(i * 0.0001, i * 0.0001) for i in range(5000)]]
        huge_coords[0].append(huge_coords[0][0])  # close ring
        huge_geom = {"type": "Polygon", "coordinates": huge_coords}
        url = build_geojson_io_url(huge_geom)
        assert url is None


class TestBuildMapLinks:
    def test_returns_both_links(self):
        links = build_map_links("sha256:abc123", SAMPLE_GEOJSON)
        assert links.geojson_io_url is not None
        assert links.thumbnail_url == "/v1/thumbnail/sha256:abc123.png"


class TestThumbnailRoute:
    @pytest.fixture
    def client(self):
        app = create_app()
        with TestClient(app) as c:
            yield c

    @patch("src.location_sentinel.routes.thumbnail.store")
    @patch("src.location_sentinel.routes.thumbnail.render_location_thumbnail", new_callable=AsyncMock)
    def test_thumbnail_200(self, mock_render, mock_store, client):
        mock_store.get_geometry.return_value = SAMPLE_GEOJSON
        mock_render.return_value = b"\x89PNG\r\n\x1a\nfake"

        resp = client.get("/v1/thumbnail/sha256:abc123.png")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "image/png"
        assert resp.headers["cache-control"] == "public, max-age=86400"
        assert resp.content == b"\x89PNG\r\n\x1a\nfake"

    @patch("src.location_sentinel.routes.thumbnail.store")
    def test_thumbnail_404(self, mock_store, client):
        mock_store.get_geometry.return_value = None

        resp = client.get("/v1/thumbnail/sha256:notfound.png")
        assert resp.status_code == 404


class TestStaticMapRender:
    async def test_render_returns_png_bytes(self):
        from src.location_sentinel.thumbnails.static_map import render_location_thumbnail

        fake_png = b"\x89PNG\r\n\x1a\ntest"
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.content = fake_png

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_resp)

        with patch("src.location_sentinel.thumbnails.static_map.httpx.AsyncClient", return_value=mock_client):
            result = await render_location_thumbnail(SAMPLE_GEOJSON)

        assert isinstance(result, bytes)
        assert result == fake_png

    def test_extract_coords_polygon(self):
        from src.location_sentinel.thumbnails.static_map import _extract_exterior_coords

        coords = _extract_exterior_coords(SAMPLE_GEOJSON)
        assert len(coords) == 5
        assert coords[0] == (-77.0365, 38.8977)

    def test_extract_coords_multipolygon(self):
        from src.location_sentinel.thumbnails.static_map import _extract_exterior_coords

        multi = {
            "type": "MultiPolygon",
            "coordinates": [SAMPLE_GEOJSON["coordinates"]],
        }
        coords = _extract_exterior_coords(multi)
        assert len(coords) == 5

    def test_extract_coords_unsupported(self):
        from src.location_sentinel.thumbnails.static_map import _extract_exterior_coords

        with pytest.raises(ValueError, match="Unsupported geometry type"):
            _extract_exterior_coords({"type": "Point", "coordinates": [0, 0]})
