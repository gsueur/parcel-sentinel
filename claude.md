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

**Request flow:** `POST /v1/locations` enqueues an async job. The job runs `features_pipeline.py` which executes three concurrent pipelines via `asyncio.gather`:
1. **S2 optical** -- STAC search (MPC), monthly best-scene selection, COG window reads (rasterio + WarpedVRT for GCP-based datasets), NDVI/NDWI/NBR/NDMI/NDSI/BSI computation, monthly aggregation
2. **S1 SAR** -- Earth Search STAC, GRD IW VV scenes, rasterio WarpedVRT reads in thread executor (`/vsis3/`, no-sign), water fraction per scene, `sar_water_freq_5y` + `sar_flood_anomaly`
3. **TerraClimate** -- OPeNDAP ASCII fetch from THREDDS, grid-cell cache, `tmax_*`, `ppt_*`, `vpd_*`, `pdsi_*` features

Clients poll `GET /v1/jobs/{job_id}` for completion. The job store is in-memory and not persisted across restarts.

**Persistence:** PostgreSQL (`POSTGRES_DSN`). The singleton `store` is `storage/postgres_store.py`. `storage/duckdb_store.py` is a legacy shim. Key tables: `location_features`, `location_timeseries`, `location_scores`, `location_geometries`, `users`, `verification_tokens`, `noaa_tidal_stations`, `noaa_tide_predictions`, `koeppen_classifications`, `customers`. Band pixel arrays (64×64 FLOAT[4096]) are cached to avoid repeat S3 traffic. TerraClimate values cached by grid cell. NOAA tide predictions cached permanently by station+date.

**Key files:**
- `src/location_sentinel/config.py` -- all thresholds, versions (`PROCESSING_VERSION`, `SCORE_VERSION`), and every env var
- `src/location_sentinel/storage/postgres_store.py` -- primary store; PostgreSQL, not DuckDB
- `src/location_sentinel/pipeline/features_pipeline.py` -- orchestrates all three pipelines, derives features + quality flags; includes new slope and momentum features (`ndvi_momentum_ratio_1y`, `ndmi_momentum_ratio_1y`, `ndwi_trend_slope_5y`, `ndmi_trend_slope_5y`)
- `src/location_sentinel/compute/features.py` -- feature helpers; `compute_recent_anomaly_ratio` computes 1y vs 5y anomaly frequency ratio (momentum signal)
- `src/location_sentinel/compute/climate_features.py` -- TerraClimate feature derivation; includes `vpd_trend_slope_5y`, `pdsi_trend_slope_5y`, `tmax_momentum_ratio_1y`, `pdsi_momentum_ratio_1y`
- `src/location_sentinel/compute/scoring.py` -- climate-zone-weighted scoring, urban branch (separate formula); implements trend-aware scoring: active episode boosts (A), 1y momentum amplifiers (B), Theil-Sen slope sub-components (C)
- `src/location_sentinel/report/html.py` -- self-contained HTML report builder (Chart.js, inline CSS/JS)
- `src/location_sentinel/routes/report.py` -- `/report` (HTML) and `/report.json` endpoints; tide level fetch/interpolation

**Versions:** Bump `PROCESSING_VERSION` in `config.py` whenever features or their computation change. `SCORE_VERSION` when scoring weights/formula change. Both are stored with cached results -- a mismatch triggers recompute.

Current versions: see `PROCESSING_VERSION` and `SCORE_VERSION` in `config.py` (the values below go stale; config.py is the source of truth).

**Trend-aware scoring (introduced in risk-v1.15.0):** Three layers applied in order after each base sub-score:
- Part A: Active episode multipliers -- `active_flood × 1.40`, `active_drought × 1.30` (non-urban), `active_fire × 1.25` (non-urban, NBR must be present)
- Part B: 1y vs 5y momentum ratios -- `ndvi_momentum_ratio_1y`, `ndmi_momentum_ratio_1y`, `pdsi_momentum_ratio_1y` amplify `drought_score`; `tmax_momentum_ratio_1y` amplifies `heat_stress_score`; ratio > 1.0 → `amp = 1 + min(0.30, (ratio-1) × 0.10)`
- Part C: Theil-Sen slope sub-components -- `ndmi_trend_slope_5y` and `pdsi_trend_slope_5y` added as weighted drought components; `vpd_trend_slope_5y` added as heat_stress component; `ndwi_trend_slope_5y` blended 15% into wetness

**Tidal zone:** On startup, `app.py` lifespan fetches NOAA CO-OPS station list if stale (>30 days). During pipeline, nearest tidal station within `TIDAL_ZONE_RADIUS_KM` (30 km) sets `is_tidal_zone=1`, adds `tidal_zone` quality flag, and suppresses `active_drought`. Report endpoints fetch hourly MSL tide predictions for each SAR scene date and interpolate to exact acquisition minute using the Sentinel-1 scene ID timestamp.

## API endpoints

All routes are under `/v1/`.

**Auth** (`routes/auth.py`): `POST /auth/register`, `GET /auth/verify`, `POST /auth/login`, `GET /auth/me` -- JWT-based auth (python-jose). Registration sends an email verification link via Resend. JWT lifetime is `JWT_EXPIRE_DAYS` (default 90).

**Locations** (`routes/locations.py`): `POST /locations` (enqueue job, returns `job_id`), `GET /locations` (user's list), `GET /locations/public`, `POST /location/{key}/regenerate`, `DELETE /location/{key}`, `DELETE /locations`.

**Features/score** (`routes/features.py`): `POST /location/features`, `POST /location/score`, `POST /location/timeseries`.

**Report**: `GET /location/{key}/report` (HTML), `GET /location/{key}/report.json`.

**Thumbnail**: `GET /thumbnail/{key}.png` -- Mapbox Static API composite.

**Jobs**: `GET /jobs`, `GET /jobs/{job_id}`.

**Customers** (admin): `GET /customers`, `POST /customers`, `GET /customers/{id}/locations`.

**Health**: `GET /health`.

## Environment variables

All vars are in `config.py` as pydantic-settings fields. Key ones not obvious from code:

| Var | Purpose |
|-----|---------|
| `POSTGRES_DSN` | PostgreSQL connection string (default: `postgresql://postgres:postgres@localhost:5432/remotesensing`) |
| `SECRET_KEY` | JWT signing secret -- required in production |
| `RESEND_API_KEY` | Resend email service key for verification emails |
| `FRONTEND_URL` | Redirect destination after email verification |
| `API_BASE_URL` | Used to build verify link in outbound emails |
| `MAPBOX_TOKEN` | Mapbox Static API token for thumbnail generation |
| `CORS_ORIGINS` | JSON array or comma-separated string |
| `DAILY_LOCATION_LIMIT` | Max new locations per user per UTC day (default 5); admins bypass |
| `ENV` | `"development"` or `"production"` |

## Frontend

Static HTML at `frontend/index.html`, deployed on Cloudflare Pages. Uses Leaflet for maps. No build step.
