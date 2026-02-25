"""TerraClimate OPeNDAP client.

Fetches monthly climate variables for a single grid cell using the University of
Idaho THREDDS server (DAP2 ASCII endpoint).  No full file download: each request
returns 12 monthly float values (~1 KB).

Grid: global 1/24° (~4 km), lat 90 N to 90 S, lon 180 W to 180 E.
Coverage: 1958–2024.
Variables: tmax, tmin, ppt, vpd, PDSI.
"""
from __future__ import annotations

import asyncio
import logging
import re

import httpx

from ..config import settings

logger = logging.getLogger(__name__)

# CF convention: actual_value = raw * scale_factor + add_offset
# Verified from THREDDS DAS metadata for each variable.
_TC_SCALE: dict[str, float] = {
    "tmax": 0.01,   # Int16, scale=0.01, offset=-99.0  → °C
    "tmin": 0.01,   # Int16, scale=0.01, offset=-99.0  → °C
    "ppt":  0.1,    # Int32, scale=0.1,  offset=0.0    → mm
    "vpd":  0.01,   # Int16, scale=0.01, offset=0.0    → kPa
    "PDSI": 0.01,   # Int16, scale=0.01, offset=-45.0  → dimensionless
}

_TC_OFFSET: dict[str, float] = {
    "tmax": -99.0,
    "tmin": -99.0,
    "ppt":   0.0,
    "vpd":   0.0,
    "PDSI": -45.0,
}

# Fill value threshold: any raw value ≤ this is treated as missing.
# Int16 fill = -32768; Int32 fill = -2147483648 (both << -32768).
_TC_FILL_VALUE = -32768


def snap_to_grid(lat: float, lon: float) -> tuple[float, float]:
    """Round lat/lon to the nearest TerraClimate 1/24° grid cell center.

    Grid formula from data documentation:
        lat_idx = round((89.979167 - lat) * 24)
        lon_idx = round((lon + 179.979167) * 24)

    Returns (snapped_lat, snapped_lon) as floats rounded to 6 decimal places.
    """
    lat_idx = round((89.979167 - lat) * 24)
    lon_idx = round((lon + 179.979167) * 24)
    snapped_lat = round(89.979167 - lat_idx / 24, 6)
    snapped_lon = round(lon_idx / 24 - 179.979167, 6)
    return snapped_lat, snapped_lon


def _grid_indices(lat: float, lon: float) -> tuple[int, int]:
    lat_idx = round((89.979167 - lat) * 24)
    lon_idx = round((lon + 179.979167) * 24)
    return lat_idx, lon_idx


def _parse_ascii(text: str, var: str) -> list[float | None]:
    """Parse an OPeNDAP DAP2 ASCII response for a Grid variable.

    TerraClimate THREDDS returns Grid-type variables with a composite header:

        varname.varname[12][1][1]
        [0][0], value
        [1][0], value
        ...
        [11][0], value

    When the sliced lat/lon dimensions are both size-1, OPeNDAP flattens them
    into a single trailing index [0].  The prefix is "varname.varname" (the
    variable name repeated for grid array vs map sections).

    Returns 12 raw Int16/Int32 values (before scale_factor/add_offset).
    Missing (fill) values are returned as None.
    """
    sep_pos = text.find("-----")
    if sep_pos == -1:
        logger.warning("TerraClimate ASCII: no separator found for %s", var)
        return [None] * 12

    data_text = text[sep_pos:].lstrip("-").strip()
    values: list[float | None] = []

    for line in data_text.split("\n"):
        line = line.strip()
        if not line:
            continue
        # Stop at the next section (map variables start with "varname.time" etc.)
        if line.startswith(f"{var}.") and not line.startswith(f"{var}.{var}"):
            break
        # Match: [time_idx][flat_idx], value  OR  [time_idx][0][0], value
        m = re.match(r"\[\d+\]\[0\](?:\[0\])?,\s*([-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)", line)
        if m:
            raw = float(m.group(1))
            values.append(None if raw <= _TC_FILL_VALUE else raw)
        if len(values) == 12:
            break

    if len(values) == 12:
        return values

    logger.warning(
        "TerraClimate ASCII: could not parse 12 values for %s (got %d)", var, len(values)
    )
    return (values + [None] * 12)[:12]


async def fetch_terraclimate_point(
    lat: float,
    lon: float,
    variables: list[str],
    years: list[int],
) -> dict[str, list[float | None]]:
    """Fetch monthly TerraClimate values for one grid cell.

    All variable × year combinations are requested concurrently (one HTTP GET
    each).  Returns {variable: [v_jan_yr1, ..., v_dec_yrN]} -- values in real
    physical units (°C, mm, kPa, dimensionless) in chronological order.

    Failed individual requests are logged and filled with None so the caller
    can still use partial results.

    Grid cell is derived from (lat, lon) via snap_to_grid before making requests.
    """
    snapped_lat, snapped_lon = snap_to_grid(lat, lon)
    lat_idx, lon_idx = _grid_indices(snapped_lat, snapped_lon)
    base_url = settings.TERRACLIMATE_THREDDS_URL

    async def _fetch_one(
        client: httpx.AsyncClient,
        var: str,
        year: int,
    ) -> tuple[str, int, list[float | None]]:
        url = (
            f"{base_url}/TerraClimate_{var}_{year}.nc.ascii"
            f"?{var}[0:11][{lat_idx}][{lon_idx}]"
        )
        try:
            r = await client.get(url)
            r.raise_for_status()
            raw_values = _parse_ascii(r.text, var)
            scale = _TC_SCALE.get(var, 1.0)
            offset = _TC_OFFSET.get(var, 0.0)
            scaled = [
                round(v * scale + offset, 3) if v is not None else None
                for v in raw_values
            ]
            return var, year, scaled
        except Exception as exc:
            logger.warning("TerraClimate fetch failed: %s %d: %s", var, year, exc)
            return var, year, [None] * 12

    async with httpx.AsyncClient(timeout=30.0) as client:
        tasks = [
            _fetch_one(client, var, year)
            for var in variables
            for year in years
        ]
        results = await asyncio.gather(*tasks)

    # Assemble into per-variable lists (all years concatenated chronologically)
    per_var_by_year: dict[str, dict[int, list[float | None]]] = {
        var: {} for var in variables
    }
    for var, year, monthly in results:
        per_var_by_year[var][year] = monthly

    output: dict[str, list[float | None]] = {}
    for var in variables:
        combined: list[float | None] = []
        for year in sorted(years):
            combined.extend(per_var_by_year[var].get(year, [None] * 12))
        output[var] = combined

    return output
