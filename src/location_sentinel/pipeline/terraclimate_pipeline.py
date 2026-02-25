"""TerraClimate pipeline.

Orchestrates DuckDB cache lookup → OPeNDAP fetch → feature derivation for a
single location's date window.
"""
from __future__ import annotations

import logging
from datetime import date

from ..compute.climate_features import compute_climate_features
from ..config import settings
from ..geometry.normalize import geojson_to_shapely
from ..stac.terraclimate_client import fetch_terraclimate_point, snap_to_grid
from ..storage.duckdb_store import store

logger = logging.getLogger(__name__)

# Maximum TerraClimate data year (update annually when new data is released).
_TC_MAX_YEAR = 2024


def _years_for_window(date_start: str, date_end: str) -> list[int]:
    """Return the list of calendar years fully or partially covered by the window."""
    start_year = date.fromisoformat(date_start).year
    end_year = min(date.fromisoformat(date_end).year, _TC_MAX_YEAR)
    return list(range(start_year, end_year + 1))


async def run_terraclimate_features(
    geom_geojson: dict,
    date_start: str,
    date_end: str,
) -> dict[str, float | None]:
    """Compute TerraClimate-derived features for a location and date window.

    Flow:
    1. Snap location centroid to the 1/24° TerraClimate grid.
    2. Query DuckDB for already-cached months.
    3. Fetch missing (variable, year) combinations from THREDDS OPeNDAP.
    4. Store new data in DuckDB.
    5. Derive and return features dict.

    Returns an empty dict with ``no_terraclimate_data`` flag on failure so
    the caller can continue with partial results.
    """
    variables = settings.TERRACLIMATE_VARIABLES
    years = _years_for_window(date_start, date_end)
    if not years:
        return {"no_terraclimate_data": 1.0}

    try:
        geom = geojson_to_shapely(geom_geojson)
        centroid = geom.centroid
        lat, lon = centroid.y, centroid.x
    except Exception as exc:
        logger.warning("TerraClimate: could not extract centroid: %s", exc)
        return {"no_terraclimate_data": 1.0}

    grid_lat, grid_lon = snap_to_grid(lat, lon)

    # ── DuckDB cache lookup ────────────────────────────────────────────────────
    cached = store.get_terraclimate_monthly(grid_lat, grid_lon, variables, years)

    # Identify which (variable, year) pairs are fully cached (all 12 months present)
    missing_combos: list[tuple[str, int]] = []
    for var in variables:
        var_cache = cached.get(var, {})
        for year in years:
            months_present = sum(1 for m in range(1, 13) if (year, m) in var_cache)
            if months_present < 12:
                missing_combos.append((var, year))

    # ── Fetch missing data from THREDDS ───────────────────────────────────────
    if missing_combos:
        missing_vars = sorted({v for v, _ in missing_combos})
        missing_years = sorted({y for _, y in missing_combos})
        logger.info(
            "TerraClimate: fetching %d var×year combos for grid (%.4f, %.4f)",
            len(missing_combos), grid_lat, grid_lon,
        )
        try:
            fetched = await fetch_terraclimate_point(lat, lon, missing_vars, missing_years)
        except Exception as exc:
            logger.warning("TerraClimate: fetch failed: %s", exc)
            fetched = {}

        # Persist new rows and update local cache dict
        rows_to_store: list[dict] = []
        for var, monthly_values in fetched.items():
            for i, year in enumerate(missing_years):
                for month_idx in range(12):
                    flat_idx = i * 12 + month_idx
                    value = monthly_values[flat_idx] if flat_idx < len(monthly_values) else None
                    month = month_idx + 1  # 1-based
                    rows_to_store.append({
                        "variable": var, "year": year, "month": month, "value": value,
                    })
                    # Update in-memory cache
                    cached.setdefault(var, {})[(year, month)] = value

        if rows_to_store:
            store.store_terraclimate_monthly(grid_lat, grid_lon, rows_to_store)
            logger.info(
                "TerraClimate: stored %d new rows for grid (%.4f, %.4f)",
                len(rows_to_store), grid_lat, grid_lon,
            )

    # ── Assemble monthly series for feature derivation ────────────────────────
    # Build {var: {(year, month): value}} restricted to the request window
    series: dict[str, dict[tuple[int, int], float | None]] = {}
    for var in variables:
        series[var] = {
            (y, m): v
            for (y, m), v in cached.get(var, {}).items()
            if y in set(years)
        }

    # Check whether we have any data at all
    total_values = sum(
        1 for var_data in series.values()
        for v in var_data.values()
        if v is not None
    )
    if total_values == 0:
        logger.warning(
            "TerraClimate: no data available for grid (%.4f, %.4f)", grid_lat, grid_lon
        )
        return {"no_terraclimate_data": 1.0}

    # ── Derive features ───────────────────────────────────────────────────────
    growing_season = (
        settings.SUBTROPICAL_SEASON_MONTHS if lat < settings.GROWING_SEASON_LAT_THRESHOLD
        else settings.TEMPERATE_SEASON_MONTHS
    )

    features = compute_climate_features(
        monthly_series=series,
        date_start=date_start,
        date_end=date_end,
        growing_season_months=growing_season,
    )
    return features
