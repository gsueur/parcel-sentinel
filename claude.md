# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Development commands

```bash
# Start the API server (port 8000)
uv run uvicorn "src.location_sentinel.app:create_app" --factory --host 0.0.0.0 --port 8000

# Run unit tests (fast, no network)
uv run pytest tests/ -k "not integration" -v

# Run a single test file
uv run pytest tests/test_scoring.py -v

# Run integration tests (requires live STAC/COG access)
uv run pytest tests/integration/ -v

# Kill stale server on port 8000
lsof -ti :8000 | xargs kill -9
```

## Architecture overview

**Request flow:** `POST /v1/locations` → `features_pipeline.py` runs three concurrent pipelines via `asyncio.gather`:
1. **S2 optical** -- STAC search (MPC), monthly best-scene selection, COG window reads (rasterio + WarpedVRT for GCP-based datasets), NDVI/NDWI/NBR/NDMI/NDSI/BSI computation, monthly aggregation
2. **S1 SAR** -- Earth Search STAC, GRD IW VV scenes, rasterio WarpedVRT reads in thread executor (`/vsis3/`, no-sign), water fraction per scene, `sar_water_freq_5y` + `sar_flood_anomaly`
3. **TerraClimate** -- OPeNDAP ASCII fetch from THREDDS, DuckDB grid-cell cache, `tmax_*`, `ppt_*`, `vpd_*`, `pdsi_*` features

**Persistence:** DuckDB only (`location_sentinel.duckdb`). All reads from `storage/duckdb_store.py` via the singleton `store`. Band pixel arrays (64×64 FLOAT[4096]) are cached to avoid repeat S3 traffic. TerraClimate values cached by grid cell. NOAA tide predictions cached permanently by station+date.

**Key files:**
- `src/location_sentinel/config.py` -- all thresholds, versions (`PROCESSING_VERSION`, `SCORE_VERSION`), config env vars
- `src/location_sentinel/storage/duckdb_store.py` -- every write method must call `self._conn.commit()` (DuckDB is NOT autocommit)
- `src/location_sentinel/pipeline/features_pipeline.py` -- orchestrates all three pipelines, derives features + quality flags
- `src/location_sentinel/compute/scoring.py` -- climate-zone-weighted scoring, urban branch (separate formula)
- `src/location_sentinel/report/html.py` -- self-contained HTML report builder (Chart.js, inline CSS/JS)
- `src/location_sentinel/routes/report.py` -- `/report` (HTML) and `/report.json` endpoints; tide level fetch/interpolation

**Versions:** Bump `PROCESSING_VERSION` in `config.py` whenever features or their computation change. `SCORE_VERSION` when scoring weights/formula change. Both are stored with cached results -- a mismatch triggers recompute.

**Tidal zone:** On startup, `app.py` lifespan fetches NOAA CO-OPS station list if stale (>30 days). During pipeline, nearest tidal station within `TIDAL_ZONE_RADIUS_KM` (30 km) sets `is_tidal_zone=1`, adds `tidal_zone` quality flag, and suppresses `active_drought`. Report endpoints fetch hourly MSL tide predictions for each SAR scene date and interpolate to exact acquisition minute using the Sentinel-1 scene ID timestamp.
