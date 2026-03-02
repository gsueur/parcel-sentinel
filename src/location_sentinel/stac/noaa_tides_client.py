from __future__ import annotations

import httpx

NOAA_STATIONS_URL = (
    "https://api.tidesandcurrents.noaa.gov/mdapi/prod/webapi/stations.json?type=waterlevels"
)


async def fetch_tidal_stations() -> list[dict]:
    """Fetch all water level stations from NOAA CO-OPS metadata API.

    Returns list of dicts: {station_id, name, lat, lon, state, tide_type}.
    Only stations where tidal=True are returned.
    """
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(NOAA_STATIONS_URL)
        resp.raise_for_status()
    data = resp.json()
    stations = []
    for s in data.get("stations", []):
        if not s.get("tidal", False):
            continue
        stations.append({
            "station_id": s["id"],
            "name": s["name"],
            "lat": float(s["lat"]),
            "lon": float(s["lng"]),
            "state": s.get("state", ""),
            "tide_type": s.get("tideType", ""),
        })
    return stations
