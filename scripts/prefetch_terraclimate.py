#!/usr/bin/env python3
"""Pre-warm TerraClimate data for stored locations.

Reads location centroids from DuckDB, snaps to the TerraClimate 1/24° grid,
fetches monthly data for all requested years from THREDDS OPeNDAP, and stores
the results so subsequent API requests hit only the DuckDB cache.

Usage
-----
# Fetch last 5 years for all stored locations
uv run python scripts/prefetch_terraclimate.py --all-locations --years-back 5

# Fetch specific years for all locations
uv run python scripts/prefetch_terraclimate.py --all-locations --years 2021 2022 2023 2024

# Fetch for a bounding box (lat_min lon_min lat_max lon_max)
uv run python scripts/prefetch_terraclimate.py --bbox 30 -100 50 -70 --years-back 5
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from datetime import date
from pathlib import Path

# Ensure the project src is on the path when invoked as a script
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from location_sentinel.config import settings
from location_sentinel.stac.terraclimate_client import fetch_terraclimate_point, snap_to_grid
from location_sentinel.storage.duckdb_store import DuckDBStore

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    datefmt="%H:%M:%S",
    level=logging.INFO,
)
logger = logging.getLogger("prefetch_tc")

# Maximum available TerraClimate year
_TC_MAX_YEAR = 2024


def _build_years(years_back: int | None, explicit_years: list[int] | None) -> list[int]:
    if explicit_years:
        return sorted(explicit_years)
    if years_back:
        current_year = date.today().year
        end_year = min(current_year - 1, _TC_MAX_YEAR)
        start_year = end_year - years_back + 1
        return list(range(start_year, end_year + 1))
    return [_TC_MAX_YEAR]


def _get_locations_from_db(
    store: DuckDBStore,
    bbox: tuple[float, float, float, float] | None,
) -> list[tuple[str, float, float]]:
    """Return [(location_key, lat, lon), ...] from DuckDB, optionally filtered by bbox."""
    from shapely.geometry import shape
    import json

    rows = store._conn.execute(
        "SELECT location_key, geojson_text FROM location_geometries"
    ).fetchall()

    results: list[tuple[str, float, float]] = []
    for location_key, geojson_text in rows:
        try:
            geom = shape(json.loads(geojson_text))
            centroid = geom.centroid
            lat, lon = centroid.y, centroid.x
            if bbox:
                lat_min, lon_min, lat_max, lon_max = bbox
                if not (lat_min <= lat <= lat_max and lon_min <= lon <= lon_max):
                    continue
            results.append((location_key, lat, lon))
        except Exception as exc:
            logger.warning("Skipping %s: %s", location_key, exc)
    return results


async def prefetch_location(
    store: DuckDBStore,
    location_key: str,
    lat: float,
    lon: float,
    variables: list[str],
    years: list[int],
) -> int:
    """Fetch and store TerraClimate data for one location. Returns number of rows stored."""
    grid_lat, grid_lon = snap_to_grid(lat, lon)

    # Check what's already cached
    cached = store.get_terraclimate_monthly(grid_lat, grid_lon, variables, years)
    missing: list[tuple[str, int]] = []
    for var in variables:
        var_cache = cached.get(var, {})
        for year in years:
            months_present = sum(1 for m in range(1, 13) if (year, m) in var_cache)
            if months_present < 12:
                missing.append((var, year))

    if not missing:
        logger.info("[%s] All data cached, skipping fetch.", location_key[:12])
        return 0

    missing_vars = sorted({v for v, _ in missing})
    missing_years = sorted({y for _, y in missing})
    logger.info(
        "[%s] Fetching %d var×year combos (grid %.4f, %.4f)",
        location_key[:12], len(missing), grid_lat, grid_lon,
    )

    try:
        fetched = await fetch_terraclimate_point(lat, lon, missing_vars, missing_years)
    except Exception as exc:
        logger.error("[%s] Fetch failed: %s", location_key[:12], exc)
        return 0

    rows_to_store: list[dict] = []
    for var, monthly_values in fetched.items():
        for i, year in enumerate(missing_years):
            for month_idx in range(12):
                flat_idx = i * 12 + month_idx
                value = monthly_values[flat_idx] if flat_idx < len(monthly_values) else None
                rows_to_store.append({
                    "variable": var,
                    "year": year,
                    "month": month_idx + 1,
                    "value": value,
                })

    if rows_to_store:
        store.store_terraclimate_monthly(grid_lat, grid_lon, rows_to_store)
        logger.info("[%s] Stored %d rows.", location_key[:12], len(rows_to_store))

    return len(rows_to_store)


async def main(args: argparse.Namespace) -> None:
    years = _build_years(args.years_back, args.years)
    variables = settings.TERRACLIMATE_VARIABLES

    logger.info("Years: %s", years)
    logger.info("Variables: %s", variables)

    store = DuckDBStore(settings.DUCKDB_PATH)
    store.connect()

    bbox = None
    if args.bbox:
        lat_min, lon_min, lat_max, lon_max = args.bbox
        bbox = (lat_min, lon_min, lat_max, lon_max)

    locations = _get_locations_from_db(store, bbox)
    if not locations:
        logger.warning("No locations found in DuckDB matching criteria.")
        store.close()
        return

    logger.info("Prefetching TerraClimate for %d locations...", len(locations))

    total_rows = 0
    for i, (location_key, lat, lon) in enumerate(locations, 1):
        logger.info("[%d/%d] %s (%.4f, %.4f)", i, len(locations), location_key[:12], lat, lon)
        n = await prefetch_location(store, location_key, lat, lon, variables, years)
        total_rows += n

    store.close()
    logger.info("Done. Total rows stored: %d", total_rows)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Pre-warm TerraClimate cache for stored locations.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--all-locations", action="store_true",
        help="Fetch for all locations stored in DuckDB.",
    )
    group.add_argument(
        "--bbox", nargs=4, type=float, metavar=("LAT_MIN", "LON_MIN", "LAT_MAX", "LON_MAX"),
        help="Only fetch for locations within this bounding box.",
    )
    year_group = parser.add_mutually_exclusive_group()
    year_group.add_argument(
        "--years-back", type=int, default=5,
        help="Number of complete years to fetch (counting back from last available). Default: 5.",
    )
    year_group.add_argument(
        "--years", nargs="+", type=int,
        help="Explicit list of calendar years to fetch (e.g. 2021 2022 2023 2024).",
    )
    return parser.parse_args()


if __name__ == "__main__":
    asyncio.run(main(parse_args()))
