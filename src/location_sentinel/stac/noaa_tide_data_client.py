from __future__ import annotations

import httpx

_NOAA_DATA_URL = "https://api.tidesandcurrents.noaa.gov/api/prod/datagetter"


async def fetch_tide_predictions(station_id: str, date_str: str) -> list[tuple[int, float]]:
    """Fetch hourly MSL tidal predictions for one station and one UTC date.

    Args:
        station_id: NOAA CO-OPS station ID (e.g. "8594900")
        date_str:   UTC date in YYYY-MM-DD format

    Returns:
        List of (hour, water_level_m) tuples (0-23 UTC). Empty on API error or
        when no predictions are available for the station/date.
    """
    compact = date_str.replace("-", "")  # YYYYMMDD
    params = {
        "station": station_id,
        "begin_date": compact,
        "end_date": compact,
        "product": "predictions",
        "datum": "MSL",
        "time_zone": "GMT",
        "interval": "h",
        "units": "metric",
        "format": "json",
    }
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(_NOAA_DATA_URL, params=params)
        resp.raise_for_status()
    data = resp.json()
    if "error" in data:
        return []
    results: list[tuple[int, float]] = []
    for rec in data.get("predictions", []):
        try:
            # "t" format: "2023-05-12 11:00"
            hour = int(rec["t"][11:13])
            level = float(rec["v"])
            results.append((hour, level))
        except (KeyError, ValueError, IndexError):
            continue
    return results
