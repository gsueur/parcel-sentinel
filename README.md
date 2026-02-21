# Location Sentinel Analytics API

On-demand climate risk indicators for any location or point of interest, derived from Sentinel-2 satellite imagery. No raw imagery is stored. Everything is computed from cloud-hosted COG assets, persisted as derived features and time series, and served via a JSON API.

---

## Table of contents

1. [What this does](#what-this-does)
2. [Architecture overview](#architecture-overview)
3. [Data source: Sentinel-2 L2A](#data-source-sentinel-2-l2a)
4. [Scene selection and cloud filtering](#scene-selection-and-cloud-filtering)
5. [Cloud masking: how bad pixels are excluded](#cloud-masking-how-bad-pixels-are-excluded)
6. [COG window reads: how imagery is downloaded](#cog-window-reads-how-imagery-is-downloaded)
7. [Spectral indices: what they measure](#spectral-indices-what-they-measure)
8. [Derived features: what gets computed](#derived-features-what-gets-computed)
9. [Risk scoring](#risk-scoring)
10. [API reference](#api-reference)
11. [Quick start for users with a pair of coordinates](#quick-start-for-users-with-a-pair-of-coordinates)
12. [Running locally](#running-locally)
13. [Configuration](#configuration)

---

## What this does

Given a location polygon or a point with coordinates, this service:

- Searches the Sentinel-2 L2A archive for satellite passes over that location
- Selects the clearest observations per month, going back up to 5 years
- Downloads exactly 64x64 native pixels (640m x 640m footprint) centered on the point for each selected scene
- Filters out clouds, cloud shadows, snow, and saturated pixels
- Computes six spectral indices per scene
- Aggregates to monthly statistics and derives long-term features
- Scores the location across four climate risk dimensions
- Returns all results as JSON and renders an HTML report with charts

Typical cold-start time (5-year window): 15-30 seconds. Cached results return instantly.

---

## Architecture overview

```
User request (geometry + date range)
        |
        v
  Input validation (Point only, WGS84)
        |
        v
  Location key = SHA-256 of normalized WKB
  (geometry hash used as stable cache key)
        |
        v
  DuckDB band cache check
  - hit: skip S3 entirely, use stored 64x64 arrays
  - miss: proceed to STAC + COG reads
        |
        v
  STAC search (AWS Earth Search v1)
  pystac-client, collection: sentinel-2-l2a
        |
        v
  Scene selection (group by month, sort by cloud cover)
  Up to 2 scenes/month, hard cap 120 scenes total
        |
        v
  Async COG window reads (async-geotiff + obstore)
  One S3 read per band per scene, max 8 concurrent
        |
        v
  SCL masking (exclude clouds, shadows, snow, saturated)
  Scene discarded if < 10% valid pixels remain
        |
        v
  Index computation (NDVI, NDWI, NDMI, NBR, NDSI, BSI)
        |
        v
  Monthly aggregation (mean per month across scenes)
        |
        v
  Long-term feature derivation
  (trends, anomaly frequencies, persistence fractions)
        |
        v
  Risk scoring (drought, wetness, fire, heat mitigation)
        |
        v
  DuckDB persistence (features, timeseries, scores, bands)
        |
        v
  JSON response + HTML report
```

---

## Data source: Sentinel-2 L2A

**Satellite:** ESA Sentinel-2 twin constellation (Sentinel-2A and Sentinel-2B)
**Revisit time:** 5 days at the equator (effective 2-3 days with both satellites)
**Resolution:** 10m for visible/NIR bands, 20m for SWIR bands
**Product level:** L2A (bottom-of-atmosphere reflectance, atmospherically corrected)
**Archive accessed:** AWS Earth Search v1 (`https://earth-search.aws.element84.com/v1`)
**Collection:** `sentinel-2-l2a`
**Access:** Public S3 bucket (`sentinel-cogs`, us-west-2), no authentication required

Bands used by this service:

| Band | Name | Resolution | Used for |
|------|------|-----------|---------|
| B02 | Blue | 10m | BSI (bare soil) |
| B03 | Green | 10m | NDWI, NDSI |
| B04 | Red | 10m | NDVI, BSI |
| B08 | NIR | 10m | NDVI, NDWI, NDMI, NBR, BSI |
| B11 | SWIR1 | 20m | NDMI, NDSI, BSI |
| B12 | SWIR2 | 20m | NBR |
| SCL | Scene Classification | 20m | Cloud / quality mask |

Only the bands actually needed for the requested metrics are fetched per scene.

---

## Scene selection and cloud filtering

The pipeline does two levels of cloud filtering: pre-selection from metadata, then pixel-level masking from the SCL band.

### Step 1: STAC metadata filtering

For a given geometry and date range, pystac-client queries Earth Search and returns all matching scenes. The raw results are then filtered down:

1. **Group by calendar month** -- scenes are bucketed into `YYYY-MM` groups.
2. **Sort by cloud cover** -- within each month, scenes are ranked by the `eo:cloud_cover` property (a scene-level cloud percentage from the catalog metadata).
3. **Select the N clearest** -- up to `MAX_SCENES_PER_MONTH` (default 2) are kept per month. This is a best-effort pre-filter; a scene with 5% cloud cover in the metadata may still have bad pixels over the specific location.
4. **Hard cap** -- total scenes across the full date range are capped at `MAX_TOTAL_SCENES` (default 120) to bound compute time.

### Step 2: Per-pixel SCL masking

After reading the imagery, the SCL (Scene Classification Layer) band provides a per-pixel quality label. Only pixels classified as valid surface are used. Everything else is masked out (set to NaN) and excluded from index computations.

See the next section for details.

### Step 3: Scene rejection

If fewer than `MIN_VALID_PIXEL_FRACTION` (default 10%) of pixels survive the SCL mask, the entire scene is discarded. This handles cases where a scene has low catalog cloud cover globally but happens to be fully cloud-covered over the specific location.

---

## Cloud masking: how bad pixels are excluded

The SCL band assigns one of 12 class values to every 20m pixel. This service uses classes **4, 5, 6, and 7** as valid. All other classes are masked.

| SCL class | Label | Treatment |
|-----------|-------|-----------|
| 0 | No data | Masked |
| 1 | Saturated / defective | Masked |
| 2 | Dark area pixels | Masked |
| 3 | Cloud shadows | Masked |
| 4 | Vegetation | **Valid** |
| 5 | Not vegetated (bare soil, urban, beach) | **Valid** |
| 6 | Water | **Valid** |
| 7 | Unclassified | **Valid** |
| 8 | Cloud medium probability | Masked |
| 9 | Cloud high probability | Masked |
| 10 | Thin cirrus | Masked |
| 11 | Snow / ice | Masked |

After masking, invalid pixels are set to NaN. All index computations use `np.nanmean`, so only valid pixels contribute to the spatial mean.

The `cloud_fraction` reported in results is the fraction of pixels that were masked out by this process (not the scene-level metadata value).

---

## COG window reads: how imagery is downloaded

Cloud-Optimized GeoTIFFs (COGs) are structured so that any rectangular window can be fetched by reading only the relevant bytes from S3, without downloading the full scene. A full Sentinel-2 scene covers ~100 x 100 km. Reading 64 pixels at 10m resolution (640m) from such a scene fetches roughly **1/150,000th** of the file.

### Read pipeline per band

1. **Parse S3 key** from the HTTPS href in the STAC item assets (e.g. `sentinel-cogs.s3.us-west-2.amazonaws.com/{key}`).
2. **Open the COG** via `async-geotiff` (backed by `obstore`), which reads only the header and overview metadata.
3. **Find the center pixel** by projecting the input point from WGS84 to the scene's native UTM CRS, then applying the inverse affine transform.
4. **Read a native-resolution window** centered on that pixel -- a single HTTP range request to S3:
   - 10m bands (B02, B03, B04, B08): read **64x64 native pixels** = 640m x 640m footprint, no resampling
   - 20m bands (B11, B12, SCL): read **32x32 native pixels** = same 640m x 640m footprint, then expanded to 64x64 by 2x pixel repeat (nearest-neighbor block duplication, no interpolation) so all arrays share the same shape for index computation

All bands for a scene are read concurrently (up to `MAX_CONCURRENT_COG_READS = 8` simultaneous S3 connections). Across scenes, concurrency is also bounded by the same semaphore to avoid overwhelming S3.

### Why 64x64?

All scenes and locations produce a fixed 64x64 pixel array. This ensures:
- Consistent array shapes across compute
- Predictable storage in DuckDB (typed `FLOAT[4096]` column)
- Band arrays are cacheable and reusable across API calls for the same location

The physical area covered by the 64x64 window:
- At 10m resolution (B02, B03, B04, B08): 64 native pixels = **640m x 640m** footprint
- At 20m resolution (B11, B12, SCL): 32 native pixels covering the same 640m x 640m footprint, expanded to 64x64 by 2x pixel repeat (no interpolation) for array alignment

### Band cache

After the first read, all 64x64 band arrays are stored in DuckDB keyed by `(location_key, scene_id, processing_version, band_key)`. Subsequent requests for the same location reuse these arrays directly, with no S3 traffic.

---

## Spectral indices: what they measure

All indices produce values in approximately [-1, +1]. They are computed pixel-by-pixel across the 64x64 array, then spatially averaged (ignoring NaN/masked pixels).

### NDVI -- Normalized Difference Vegetation Index

```
NDVI = (B08 - B04) / (B08 + B04)
```

Measures green photosynthetic vegetation density. Healthy dense vegetation reflects strongly in the near-infrared (B08) and absorbs red light (B04).

| Value range | Interpretation |
|-------------|---------------|
| 0.6 -- 0.9 | Dense healthy vegetation (forest, cropland in season) |
| 0.3 -- 0.6 | Moderate vegetation |
| 0.1 -- 0.3 | Sparse or stressed vegetation |
| < 0.1 | Bare soil, rock, urban, water |
| < 0 | Water, snow, or clouds |

---

### NDWI -- Normalized Difference Water Index (McFeeters 1996)

```
NDWI = (B03 - B08) / (B03 + B08)
```

Detects open surface water. Water reflects green light and absorbs NIR strongly, so water pixels produce positive NDWI.

| Value range | Interpretation |
|-------------|---------------|
| > 0 | Open water likely present |
| -0.1 -- 0 | Wet soil, transitional |
| < -0.1 | Dry surface, vegetation, built-up |

Note: this is the McFeeters (1996) formulation using Green and NIR, locked in `processing_version s2l2a-v1.2.0`. It targets open water bodies, not vegetation moisture (see NDMI for that).

---

### NDMI -- Normalized Difference Moisture Index

```
NDMI = (B08 - B11) / (B08 + B11)
```

Measures leaf and canopy water content. Uses NIR and SWIR1. Unlike NDWI, this is sensitive to moisture within vegetation canopy, not open water.

| Value range | Interpretation |
|-------------|---------------|
| > 0.2 | High vegetation moisture, no stress |
| 0 -- 0.2 | Moderate moisture |
| < 0 | Vegetation moisture stress, possible drought conditions |

---

### NBR -- Normalized Burn Ratio

```
NBR = (B08 - B12) / (B08 + B12)
```

Detects burned areas and quantifies burn severity. Healthy vegetation has high NIR and low SWIR2; recently burned surfaces lose NIR reflectance and increase SWIR2.

| Value range | Interpretation |
|-------------|---------------|
| > 0.3 | Healthy unburned vegetation |
| 0.1 -- 0.3 | Low burn severity or recovering |
| < 0.1 | Burn signal present |
| < -0.1 | High burn severity |

The fire exposure feature counts months where NBR < 0.1 (threshold configurable via `NBR_BURN_THRESHOLD`).

---

### NDSI -- Normalized Difference Snow Index

```
NDSI = (B03 - B11) / (B03 + B11)
```

Detects snow and ice. Snow reflects strongly in visible green and absorbs SWIR almost completely.

| Value range | Interpretation |
|-------------|---------------|
| > 0.4 | Snow or ice cover (threshold configurable) |
| 0.1 -- 0.4 | Partial snow or wet snow |
| < 0.1 | No snow |

Note: SCL class 11 (snow/ice) pixels are excluded from the valid mask. NDSI is computed after masking, so it only fires when the SCL misclassifies snow as another class -- which is rare but does occur in complex terrain.

---

### BSI -- Bare Soil Index

```
BSI = (B11 + B04 - B08 - B02) / (B11 + B04 + B08 + B02)
```

Multi-band bare soil index. Combines SWIR1 and Red (bright in bare soil) against NIR and Blue (suppressed by soil, enhanced by vegetation). More robust to lighting variation than single-band approaches.

| Value range | Interpretation |
|-------------|---------------|
| > 0.2 | Clearly exposed bare soil |
| 0 -- 0.2 | Mixed or transitional surface |
| < 0 | Vegetation-covered ground |

---

## Derived features: what gets computed

Over the full date window (typically 5 years of monthly observations), the following long-term features are derived from the monthly time series:

| Feature | Description |
|---------|-------------|
| `ndvi_mean_5y` | Mean NDVI across all valid observations |
| `ndvi_trend_slope_5y` | Theil-Sen robust slope, NDVI units/year. Negative = declining vegetation |
| `ndvi_anomaly_freq_5y` | Fraction of months where NDVI was > 0.1 below that month's historical mean |
| `ndwi_wetness_persistence_5y` | Fraction of months with NDWI > 0 (surface water present) |
| `ndmi_mean_5y` | Mean NDMI over the period |
| `ndmi_moisture_stress_freq_5y` | Fraction of months with NDMI < 0 (vegetation moisture stress) |
| `nbr_mean_5y` | Mean NBR over the period |
| `nbr_burn_freq_5y` | Fraction of months with NBR < 0.1 (burn signal present) |
| `ndsi_snow_persistence_5y` | Fraction of months with NDSI > 0.4 (snow covered) |
| `bsi_mean_5y` | Mean BSI over the period |
| `bsi_bare_soil_freq_5y` | Fraction of months with BSI > 0 (bare soil exposed) |
| `canopy_proxy_50m` | Mean peak-season NDVI within 50m of location center |
| `canopy_proxy_200m` | Mean peak-season NDVI within 200m of location center |
| `quality_score` | Combined score [0-1] of temporal coverage and cloud clarity |

### Trend computation

`ndvi_trend_slope_5y` uses **Theil-Sen regression** (median of all pairwise slopes), which is robust to outliers. A minimum of 6 observations is required. The slope is expressed in index units per year (converted from per-month).

### Anomaly frequency

Each month is compared to a **monthly climatology** (the mean for that calendar month across all years in the window). An anomaly is defined as any observation more than 0.1 NDVI units below its climatological mean. This isolates genuine departures from seasonal norms rather than penalizing naturally low-vegetation periods.

### Quality score

```
quality = coverage * clarity * confidence

where:
  coverage   = months_observed / months_total
  clarity    = 1 - mean_cloud_fraction
  confidence = 1.0 if coverage >= 0.5, else coverage / 0.5
```

A quality score above 0.7 indicates a reliable result. Below 0.4, interpret with caution.

---

## Risk scoring

Four sub-scores and a composite are computed from the derived features. All scores are integers in [0, 100].

**Convention:**
- `drought_score`, `wetness_score`, `fire_exposure_score`: **higher = more risk**
- `heat_mitigation_score`: **higher = more canopy = less heat risk**
- `composite_score`: **higher = more overall climate risk**

### Drought score (0-100)

Weighted combination of:

| Component | Weight | Mapping |
|-----------|--------|---------|
| NDVI anomaly frequency | 25% | 0-1 fraction -> 0-100 |
| NDVI trend slope | 25% | [-0.05, +0.05]/yr -> [100, 0] |
| NDVI mean | 20% | [0, 0.8] -> [100, 0] |
| NDMI moisture stress frequency | 30% | 0-1 fraction -> 0-100 |

A score of 0 means no drought signal. A score of 80+ indicates persistent and worsening vegetation water stress.

### Wetness score (0-100)

```
wetness_score = ndwi_wetness_persistence_5y * 100
```

Directly reflects how often open water is detected over the location. 0 = never wet, 100 = water present every month. High wetness scores (> 50) suggest chronic flooding or permanent water body.

### Fire exposure score (0-100)

```
fire_exposure_score = nbr_burn_freq_5y * 100
```

Fraction of months with a detectable burn signal (NBR < 0.1). 0 = no fire history in the window, 30 = burn signal 30% of months, 100 = persistently burned (extreme).

If no NBR data is available, defaults to 0.

### Heat mitigation score (0-100)

```
heat_mitigation_score = canopy_proxy_200m / 0.8 * 100
```

Higher canopy = more shade = better heat mitigation. A score of 80+ indicates dense urban tree canopy or forest. A score near 0 indicates fully exposed impervious or bare surface. Note: this score direction is **inverted** in the composite (high mitigation = lower risk).

### Composite score (0-100)

```
composite = 0.35 * drought_score
          + 0.25 * wetness_score
          + 0.20 * fire_exposure_score
          + 0.20 * (100 - heat_mitigation_score)
```

A composite below 25 is low overall risk. Above 65 indicates a location under significant combined climate stress.

---

## API reference

Base URL: `http://localhost:8000` (local) or your deployed host.
Interactive docs: `http://localhost:8000/docs`

---

### POST /v1/location/timeseries

Compute or retrieve the monthly time series for a location.

**Request**

```json
{
  "geometry": {
    "type": "Point",
    "coordinates": [-77.036, 38.897]
  },
  "date_start": "2021-01-01",
  "date_end": "2026-01-01",
  "metrics": ["ndvi", "ndwi", "ndmi", "nbr", "ndsi", "bsi"],
  "cadence": "monthly",
  "max_scenes_per_month": 2,
  "force_recompute": false
}
```

`geometry` must be a `Point` in WGS84. The analysis window is 64x64 native pixels (640m x 640m) centered on the point.

**Response**

```json
{
  "location_key": "a1b2c3",
  "processing_version": "s2l2a-v1.2.0",
  "series": {
    "ndvi": [
      { "month": "2021-01", "mean": 0.42, "obs": 2, "cloud": 0.04 },
      { "month": "2021-02", "mean": 0.38, "obs": 1, "cloud": 0.11 }
    ],
    "ndwi": []
  },
  "quality": {
    "months_total": 61,
    "months_observed": 58,
    "mean_cloud_fraction": 0.09,
    "flags": []
  },
  "cache": { "hit": false, "age_seconds": 0 },
  "map_links": {
    "geojson_io_url": "https://geojson.io/#data=...",
    "thumbnail_url": "/v1/thumbnail/a1b2c3.png"
  }
}
```

---

### POST /v1/location/features

Compute long-term derived features. Runs the timeseries pipeline internally if not cached.

**Request**

```json
{
  "geometry": {
    "type": "Point",
    "coordinates": [-77.036, 38.897]
  },
  "date_start": "2021-01-01",
  "date_end": "2026-01-01",
  "metrics": ["ndvi", "ndwi", "ndmi", "nbr", "ndsi", "bsi"],
  "buffers_m": [50, 200],
  "force_recompute": false
}
```

**Response**

```json
{
  "location_key": "a1b2c3",
  "processing_version": "s2l2a-v1.2.0",
  "date_window": { "start": "2021-01-01", "end": "2026-01-01" },
  "features": {
    "ndvi_mean_5y": 0.42,
    "ndvi_trend_slope_5y": -0.0031,
    "ndvi_anomaly_freq_5y": 0.18,
    "ndwi_wetness_persistence_5y": 0.09,
    "ndmi_mean_5y": 0.12,
    "ndmi_moisture_stress_freq_5y": 0.25,
    "nbr_mean_5y": 0.31,
    "nbr_burn_freq_5y": 0.0,
    "ndsi_snow_persistence_5y": 0.0,
    "bsi_mean_5y": -0.05,
    "bsi_bare_soil_freq_5y": 0.12,
    "canopy_proxy_50m": 0.36,
    "canopy_proxy_200m": 0.41,
    "quality_score": 0.87
  },
  "quality": { "months_total": 61, "months_observed": 58, "mean_cloud_fraction": 0.09, "flags": [] },
  "cache": { "hit": false, "age_seconds": 0 }
}
```

---

### POST /v1/location/score

Compute the four risk sub-scores and composite. Runs features pipeline internally if needed.

**Request**

```json
{
  "geometry": {
    "type": "Point",
    "coordinates": [-77.036, 38.897]
  },
  "date_end": "2026-01-01",
  "lookback_years": 5,
  "force_recompute": false
}
```

**Response**

```json
{
  "location_key": "a1b2c3",
  "score_version": "risk-v1.1.0",
  "scores": {
    "drought_score": 38,
    "wetness_score": 9,
    "fire_exposure_score": 0,
    "heat_mitigation_score": 51,
    "composite_score": 31
  },
  "explain": {
    "top_factors": [
      { "name": "ndmi_moisture_stress_freq_5y", "direction": "positive", "weight": 0.30 },
      { "name": "ndvi_trend_slope_5y", "direction": "negative", "weight": 0.25 }
    ]
  }
}
```

---

### GET /v1/location/{location_key}/report

Returns a self-contained HTML page with:
- Location thumbnail (Mapbox satellite)
- Timeseries charts for all computed indices
- Gradient reference bars with actual min/max markers
- Feature table grouped by theme
- Risk score gauges with explanations

The `location_key` is returned by any of the POST endpoints above. The location geometry must have been stored by a prior POST request.

Example: `GET /v1/location/a1b2c3/report`

---

### GET /v1/thumbnail/{location_key}.png

Returns a 300x200 PNG map thumbnail showing the location boundary on a Mapbox basemap.
The viewport covers 1500m of landscape context around the location.

Response: `image/png`, `Cache-Control: public, max-age=86400`.

---

### GET /v1/locations

Returns all stored locations ordered by last-updated timestamp.

**Response**

```json
[
  {
    "location_key": "a1b2c3",
    "name": "My location",
    "customer_id": "abc123",
    "customer_name": "Acme Corp",
    "centroid": [-77.036, 38.897],
    "updated_at": "2026-02-21T10:00:00Z",
    "report_url": "/v1/location/a1b2c3/report",
    "thumbnail_url": "/v1/thumbnail/a1b2c3.png"
  }
]
```

---

### GET /v1/health

```json
{ "status": "ok", "db": true }
```

---

## Quick start for users with a pair of coordinates

You have coordinates for a location and want to understand its climate risk profile over the past 5 years.

### Step 1: Get the monthly time series

```bash
curl -s -X POST http://localhost:8000/v1/location/timeseries \
  -H 'Content-Type: application/json' \
  -d '{
    "geometry": {
      "type": "Point",
      "coordinates": [-118.243, 34.052]
    },
    "date_start": "2021-01-01",
    "date_end": "2026-01-01",
    "metrics": ["ndvi", "ndwi", "ndmi", "nbr", "ndsi", "bsi"]
  }' | jq .
```

The first call will take 15-30 seconds (live S3 reads). The response includes your `location_key`.

### Step 2: Get the risk scores

```bash
curl -s -X POST http://localhost:8000/v1/location/score \
  -H 'Content-Type: application/json' \
  -d '{
    "geometry": {
      "type": "Point",
      "coordinates": [-118.243, 34.052]
    },
    "date_end": "2026-01-01",
    "lookback_years": 5
  }' | jq .scores
```

This call is instant if the timeseries was already computed (same geometry = same location key = cache hit).

### Step 3: Open the HTML report

```
http://localhost:8000/v1/location/{location_key}/report
```

Replace `{location_key}` with the value from the timeseries response. The report shows charts for all indices, a feature summary with contextual descriptions, and the four risk scores.

### Geometry: Point only

Only `Point` geometries are accepted. The analysis window is always 64x64 native pixels (640m x 640m at 10m resolution) centered on the given point. This is consistent and comparable across all locations regardless of location size.

### Interpreting results

| Score | 0-25 | 25-50 | 50-75 | 75-100 |
|-------|------|-------|-------|--------|
| Drought | No signal | Mild stress | Significant stress | Severe |
| Wetness | Never wet | Seasonally wet | Frequently flooded | Permanent water |
| Fire | No history | Low exposure | Moderate exposure | High exposure |
| Heat mitigation | Fully exposed | Sparse cover | Partial shade | Dense canopy |
| Composite | Low risk | Moderate | Elevated | High risk |

---

## Running locally

**Requirements:** Python 3.12+, [uv](https://github.com/astral-sh/uv)

```bash
# Install dependencies
uv sync

# Start the server
uv run python main.py
```

Server runs on `http://localhost:8000`. Interactive API docs at `http://localhost:8000/docs`.

The DuckDB database file (`location_sentinel.duckdb`) is created automatically on first run. All computed features, time series, and band arrays are persisted there.

### Running tests

```bash
# Unit tests (no network required)
uv run pytest tests/ -k "not integration" -v

# Integration tests (live S3 + STAC, requires internet)
RUN_INTEGRATION_TESTS=1 uv run pytest tests/integration/ -v
```

---

## Configuration

All settings are read from environment variables. Defaults are production-grade and work out of the box.

| Variable | Default | Description |
|----------|---------|-------------|
| `DUCKDB_PATH` | `location_sentinel.duckdb` | Path to DuckDB file |
| `STAC_ENDPOINTS` | AWS Earth Search v1 | Comma-separated STAC endpoint list |
| `STAC_COLLECTION` | `sentinel-2-l2a` | STAC collection name |
| `AWS_SENTINEL_BUCKET` | `sentinel-cogs` | Public S3 bucket name |
| `AWS_SENTINEL_REGION` | `us-west-2` | S3 bucket region |
| `MAX_SCENES_PER_MONTH` | `2` | Max scenes selected per calendar month |
| `MAX_TOTAL_SCENES` | `120` | Hard cap on scenes per request |
| `MAX_CONCURRENT_COG_READS` | `8` | Max parallel S3 connections |
| `COG_WINDOW_SIZE` | `64` | Native pixel count read per band (10m bands: 64x64 = 640m; 20m bands: 32x32 = 640m, expanded to 64x64 by block repeat) |
| `MIN_VALID_PIXEL_FRACTION` | `0.1` | Minimum valid pixel fraction to use a scene |
| `MAX_PARCEL_AREA_SQM` | `5000000` | Max location area (500 ha) |
| `DEFAULT_POINT_BUFFER_M` | `100.0` | Buffer radius applied to Point inputs |
| `PROCESSING_VERSION` | `s2l2a-v1.2.0` | Version tag for features cache key |
| `SCORE_VERSION` | `risk-v1.1.0` | Version tag for scores cache key |
| `CACHE_TTL_SECONDS` | `604800` | In-memory cache TTL (7 days) |
| `NDVI_ANOMALY_THRESHOLD` | `0.1` | Anomaly threshold (NDVI units below climatology) |
| `NDWI_WET_THRESHOLD` | `0.0` | NDWI threshold for wetness persistence |
| `NDMI_STRESS_THRESHOLD` | `0.0` | NDMI threshold for moisture stress |
| `NBR_BURN_THRESHOLD` | `0.1` | NBR threshold for burn detection |
| `NDSI_SNOW_THRESHOLD` | `0.4` | NDSI threshold for snow detection |
| `BSI_BARE_THRESHOLD` | `0.0` | BSI threshold for bare soil detection |
| `MAPBOX_TOKEN` | (set in config) | Mapbox public token for thumbnails |
| `THUMBNAIL_CONTEXT_BUFFER_M` | `1500.0` | Landscape context buffer for thumbnail viewport |
| `LOG_LEVEL` | `INFO` | Logging level |

To override, set environment variables before starting:

```bash
MAX_SCENES_PER_MONTH=3 MAX_CONCURRENT_COG_READS=16 uv run python main.py
```
