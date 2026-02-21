from __future__ import annotations

# Earth Search v1 uses common names as asset keys, not band numbers.
EARTH_SEARCH_BAND_MAP: dict[str, str] = {
    "B02": "blue",
    "B03": "green",
    "B04": "red",
    "B08": "nir",
    "B11": "swir16",
    "B12": "swir22",
    "SCL": "scl",
}


def earth_search_asset_key(band_key: str) -> str:
    """Convert internal band key (e.g. 'B04') to Earth Search asset key (e.g. 'red')."""
    return EARTH_SEARCH_BAND_MAP.get(band_key, band_key.lower())
