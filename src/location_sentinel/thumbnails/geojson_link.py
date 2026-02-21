from __future__ import annotations

import json
import urllib.parse

from ..config import settings


def build_geojson_io_url(geojson_geometry: dict) -> str | None:
    """Build a geojson.io URL for the given GeoJSON geometry.

    Returns None if the resulting URL exceeds the configured max length.
    """
    feature_collection = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": geojson_geometry,
                "properties": {},
            }
        ],
    }
    payload = json.dumps(feature_collection, separators=(",", ":"))
    encoded = urllib.parse.quote(payload, safe="")
    url = f"https://geojson.io/#data=data:application/json,{encoded}"
    if len(url) > settings.GEOJSON_IO_MAX_URL_LENGTH:
        return None
    return url
