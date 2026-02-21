# Parcel Sentinel Analytics API (Path A)
Specification for implementation in FastAPI using STAC search + COG window reads, storing only derived parcel features.

Owner: Guillaume Sueur  
Date: 2026-02-16  
Status: Draft v0.1

## 1. Purpose
Provide long-term climate risk indicators for any parcel in the contiguous United States using Sentinel imagery, computed on demand from cloud-hosted COG assets discovered via STAC, and persisted as derived features plus optional time series.

Primary focus: B (long-term scoring).  
Secondary future focus: A (near real-time event detection) is out of scope for this version.

## 2. Non-goals
- Do not store raw Sentinel imagery or scene archives.
- Do not build a nationwide raster warehouse.
- Do not implement UI, only API.
- Do not implement billing or auth beyond API key scaffold.

## 3. High-level design
Request flow:
1) Client sends parcel geometry (polygon preferred; point allowed with buffer) and date range.
2) Service searches STAC for Sentinel-2 L2A items intersecting geometry and time window.
3) Service selects a limited set of observations (monthly best, least-cloudy, etc).
4) Service reads required bands from COG assets using window reads only.
5) Service computes indices per observation and aggregates to monthly series.
6) Service derives long-term features and a risk score.
7) Service caches and persists results keyed by geometry hash, date window, and processing version.
8) Service returns JSON with features, optional time series, and quality metadata.

Core principle:
- Compute is on demand.
- Persist only derived numeric outputs (features and time series), not imagery.

## 4. Data sources
### 4.1 Sentinel-2 L2A (baseline)
- STAC catalogs to support: configurable list
  - Preferred default: Microsoft Planetary Computer STAC
  - Alternative: Copernicus Data Space STAC
  - Optional: AWS Earth Search
- Assets: COG reflectance bands and QA layers
- Required bands for MVP:
  - B04 (Red)
  - B08 (NIR)
  - B03 (Green) optional
  - B11 (SWIR1) optional for burn or moisture extensions
  - SCL (Scene Classification Layer) or QA mask
- Resolution handling:
  - Use 10m bands for NDVI.
  - If mixing 20m, resample consistently.

### 4.2 Parcel geometry
Inputs:
- Polygon geometry in WGS84 GeoJSON is primary.
- Point input supported with configurable buffer radius.

Optional:
- Parcel_id resolution is out of scope unless a client-provided lookup exists.

## 5. Outputs
### 5.1 Time series (monthly cadence)
For each metric:
- monthly_mean
- monthly_p50, monthly_p95 optional
- observation_count
- cloud_fraction_estimate

### 5.2 Derived parcel features
Example feature set for MVP:
- ndvi_mean_5y
- ndvi_p10_5y, ndvi_p90_5y optional
- ndvi_trend_slope_5y (robust slope per month or per year)
- ndvi_anomaly_freq_5y (fraction of months below threshold)
- ndwi_wetness_persistence_5y (fraction of months above threshold)
- canopy_proxy_50m, canopy_proxy_200m (mean peak season NDVI in buffers)
- quality_score (0..1) and flags

### 5.3 Risk scoring (v1)
Return sub-scores and composite:
- drought_score (0..100)
- wetness_score (0..100)
- heat_mitigation_score (0..100) derived from canopy proxy, not temperature in MVP
- composite_score (0..100)
Scoring must be deterministic and versioned.

## 6. API specification
Base URL: /v1

### 6.1 POST /parcel/features
Compute or retrieve derived features for a parcel.

Request JSON:
```json
{
  "geometry": {
    "type": "Polygon",
    "coordinates": [[
      [-77.0365, 38.8977],
      [-77.0355, 38.8977],
      [-77.0355, 38.8967],
      [-77.0365, 38.8967],
      [-77.0365, 38.8977]
    ]]
  },
  "date_start": "2021-02-01",
  "date_end": "2026-02-01",
  "metrics": ["ndvi", "ndwi", "canopy_proxy"],
  "cadence": "monthly",
  "buffers_m": [50, 200],
  "force_recompute": false
}
```

Response JSON:
```json
{
  "parcel_key": "sha256:a1b2c3d4e5f6...",
  "processing_version": "s2l2a-v1.0.0",
  "date_window": { "start": "2021-02-01", "end": "2026-02-01" },
  "features": {
    "ndvi_mean_5y": 0.42,
    "ndvi_trend_slope_5y": -0.0031,
    "ndvi_anomaly_freq_5y": 0.18,
    "ndwi_wetness_persistence_5y": 0.09,
    "canopy_proxy_50m": 0.36,
    "canopy_proxy_200m": 0.41,
    "quality_score": 0.87
  },
  "quality": {
    "months_total": 60,
    "months_observed": 56,
    "mean_cloud_fraction": 0.12,
    "flags": []
  },
  "cache": { "hit": true, "age_seconds": 12345 },
  "map_links": {
    "geojson_io_url": "https://geojson.io/#data=data:application/json,...",
    "thumbnail_url": "/v1/thumbnail/sha256:a1b2c3d4e5f6....png"
  }
}
```
Errors:
400 invalid geometry or date range
422 geometry too large (configurable max area)
429 rate limit
500 computation failure (include trace_id)

### 6.2 POST /parcel/timeseries
Return monthly time series for requested metrics.
Request JSON:
```json
{
  "geometry": {
    "type": "Polygon",
    "coordinates": [[
      [-77.0365, 38.8977],
      [-77.0355, 38.8977],
      [-77.0355, 38.8967],
      [-77.0365, 38.8967],
      [-77.0365, 38.8977]
    ]]
  },
  "date_start": "2021-02-01",
  "date_end": "2026-02-01",
  "metrics": ["ndvi", "ndwi"],
  "cadence": "monthly",
  "max_scenes_per_month": 2,
  "force_recompute": false
}
```
Response JSON:
```json
{
  "parcel_key": "sha256:a1b2c3d4e5f6...",
  "processing_version": "s2l2a-v1.0.0",
  "series": {
    "ndvi": [
      { "month": "2021-02", "mean": 0.18, "obs": 1, "cloud": 0.08 },
      { "month": "2021-03", "mean": 0.25, "obs": 2, "cloud": 0.05 },
      { "month": "2021-04", "mean": 0.41, "obs": 2, "cloud": 0.03 },
      "..."
    ],
    "ndwi": [
      { "month": "2021-02", "mean": -0.05, "obs": 1, "cloud": 0.08 },
      { "month": "2021-03", "mean": -0.02, "obs": 2, "cloud": 0.05 },
      { "month": "2021-04", "mean": 0.04, "obs": 2, "cloud": 0.03 },
      "..."
    ]
  },
  "quality": {
    "months_total": 60,
    "months_observed": 56,
    "mean_cloud_fraction": 0.10,
    "flags": []
  },
  "cache": { "hit": false, "age_seconds": 0 },
  "map_links": {
    "geojson_io_url": "https://geojson.io/#data=data:application/json,...",
    "thumbnail_url": "/v1/thumbnail/sha256:a1b2c3d4e5f6....png"
  }
}
```
### 6.3 POST /parcel/score
Return the sub-scores and composite.
Request JSON:
```json
{
  "geometry": {
    "type": "Polygon",
    "coordinates": [[
      [-77.0365, 38.8977],
      [-77.0355, 38.8977],
      [-77.0355, 38.8967],
      [-77.0365, 38.8967],
      [-77.0365, 38.8977]
    ]]
  },
  "date_end": "2026-02-01",
  "lookback_years": 5,
  "force_recompute": false
}
```
Response JSON:
```json
{
  "parcel_key": "sha256:a1b2c3d4e5f6...",
  "score_version": "risk-v1.0.0",
  "scores": {
    "drought_score": 62,
    "wetness_score": 28,
    "heat_mitigation_score": 71,
    "composite_score": 54
  },
  "explain": {
    "top_factors": [
      { "name": "ndvi_trend_slope_5y", "direction": "negative", "weight": 0.35 },
      { "name": "ndwi_wetness_persistence_5y", "direction": "positive", "weight": 0.25 }
    ]
  },
  "map_links": {
    "geojson_io_url": "https://geojson.io/#data=data:application/json,...",
    "thumbnail_url": "/v1/thumbnail/sha256:a1b2c3d4e5f6....png"
  }
}
```

### 6.4 GET /v1/thumbnail/{parcel_key}.png
Return a static PNG thumbnail (300x200) of the parcel boundary on an OSM basemap.
The `parcel_key` must have been created by a prior POST request (geometry is stored in DuckDB).

Response: `image/png` with `Cache-Control: public, max-age=86400`.

Errors:
404 parcel geometry not found (no prior POST for this key)
500 tile fetch or render failure


## 7. Computation details
### 7.1 Scene selection strategy
Goal: keep computations bounded per request.
Default selection algorithm:
Group STAC items by month.
For each month, pick up to K items with lowest cloud cover estimate.
Prefer items with larger overlap area with parcel bbox.
If no cloud metadata, fallback to SCL/QA mask sampling.
Config:
max_months = (date_end - date_start) months
max_scenes_per_month default 1 or 2
hard cap total scenes per request, default 120

### 7.2 Masking and QA
Use SCL classes to exclude clouds and shadows.
If SCL not available, use QA60 or catalog-specific cloud mask.
For each observation, compute:
valid_pixel_count
total_pixel_count
cloud_fraction_estimate
if valid_pixel_count below threshold, mark as low confidence

### 7.3 Indices
NDVI:
(NIR - RED) / (NIR + RED)
NDWI (choose one and version it):
Option 1 (McFeeters):
(GREEN - NIR) / (GREEN + NIR)
Option 2 (Gao, moisture):
(NIR - SWIR) / (NIR + SWIR)
Pick one for MVP, declare in processing_version.
Canopy proxy:
For each year, take peak NDVI month in growing season window (configurable by latitude or fixed May-Sep).
Compute mean of peak NDVI within buffers around parcel.

### 7.4 Trend and anomaly
Convert monthly series to anomaly vs monthly climatology (mean per calendar month across years).
Drought frequency:
months where anomaly < -T (default T = 0.1 NDVI units), divided by observed months.
Trend slope:
robust regression on monthly means (Theil-Sen or Huber) to reduce outlier sensitivity.
Return slope per year.

### 7.5 Geometry handling
Input is WGS84.
Reproject geometry to scene CRS for clipping or use rasterio warping.
Enforce maximum parcel area (config) to prevent abuse.
Simplify polygon if vertex count exceeds threshold (config) while preserving topology.

## 8. Persistence and caching
### 8.1 Keys
parcel_key:
sha256 of normalized geometry (WKB after rounding coordinates) + buffer parameters
cache_key:
parcel_key + date_start + date_end + metrics + cadence + processing_version + scoring_version

### 8.2 Layers
In-memory or Redis cache
Store full JSON response for /features and /timeseries
TTL default 7 days
Feature store (durable)
DuckDB or Postgres
Tables:
parcel_features(parcel_key, processing_version, date_start, date_end, features_json, quality_json, updated_at)
parcel_timeseries(parcel_key, processing_version, cadence, metric, series_json, updated_at)
parcel_scores(parcel_key, score_version, lookback_years, scores_json, updated_at)
parcel_geometries(parcel_key PK, geojson_text, updated_at) -- stores geometry for thumbnail rendering via GET endpoint
Metadata cache
STAC search responses cached by bbox tile + month + collection
### 8.3 Recompute policy
If feature exists and date window is within stored window, reuse.
If request extends window, compute only missing months and merge.
force_recompute bypasses cache and overwrites store.

## 9. Performance requirements
P95 latency targets (typical residential parcel, 5y window, monthly cadence, 1 scene/month):
/features: < 6 seconds warm, < 15 seconds cold
/timeseries: < 10 seconds warm, < 25 seconds cold
/thumbnail: < 2 seconds (tile fetch + render, cached after first call)
Hard timeout per request: configurable, default 60 seconds
Concurrency:
Async STAC calls
Thread pool for raster window reads and math
Cap parallel COG reads per request, default 8

## 10. Implementation constraints and libraries
Preferred Python stack:
fastapi, uvicorn
pystac-client for STAC search
rasterio for reading COG windows
shapely for geometry ops
pyproj for reprojection
numpy for math
pandas optional for monthly aggregation
duckdb for persistence (or psycopg for Postgres)
httpx for async requests
staticmap for thumbnail generation (OSM tiles + Pillow)
Avoid:
heavyweight distributed frameworks for MVP.
## 11. Configuration
Environment variables:
STAC_ENDPOINTS (comma-separated, ordered preference)
STAC_COLLECTION (default sentinel-2-l2a)
MAX_SCENES_PER_MONTH
MAX_TOTAL_SCENES
MAX_PARCEL_AREA_SQM
CACHE_TTL_SECONDS
PROCESSING_VERSION
SCORE_VERSION
DUCKDB_PATH or POSTGRES_DSN
REDIS_URL optional
API_KEY optional
THUMBNAIL_WIDTH (default 300)
THUMBNAIL_HEIGHT (default 200)
THUMBNAIL_CACHE_TTL (default 86400)
GEOJSON_IO_MAX_URL_LENGTH (default 8000)

## 12. Observability
Structured logs JSON with trace_id
Metrics:
request_count, latency_ms by endpoint
cache_hit_rate
stac_search_latency
cog_read_bytes, cog_read_count
computation_time_ms
error rates by category
Tracing: OpenTelemetry optional

## 13. Security
Input validation and size limits
Rate limiting per API key or IP
Deny geometries exceeding max vertices or area
Do not log full geometry, log geometry hash only

## 14. Testing
Unit tests:
geometry normalization hashing
NDVI and NDWI correctness
QA masking logic
monthly aggregation
trend and anomaly calculations
cache key stability
Integration tests:
live STAC search against chosen endpoint (can be gated)
COG reads for a known small AOI and date range
end-to-end response schema validation
Golden fixtures:
Use a known parcel polygon and date range where you record expected outputs within tolerance.

## 15. Deliverables
Claude Code should implement:
FastAPI app with the three POST endpoints, thumbnail GET endpoint, and health
STAC client module with pluggable endpoints
COG reading module supporting window reads and masking
Metrics computation module (NDVI, NDWI, canopy proxy, aggregation, trend, anomaly)
Persistence layer (DuckDB first, Postgres optional)
Caching layer (in-memory first, Redis optional)
Config module and sane defaults
Tests and minimal docs for running locally

## 16. Open decisions
Choose NDWI definition for MVP and lock it in processing_version.
Choose primary STAC endpoint default for production.
Decide DuckDB vs Postgres as authoritative store.
Decide whether buffers are computed in meters using local projection or geodesic buffering.

## 17. Future extensions (not in scope)
Sentinel-1 flood detection and recurrence
Subsidence via InSAR
Regional LST from Sentinel-3 or other thermal sources
Batch processing endpoint for portfolio runs
Async job queue for long requests
Prewarming for frequently requested regions