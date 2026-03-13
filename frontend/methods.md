# Location Sentinel -- Scientific Methods Reference

**Version:** processing `s2l2a-v1.27.0` / scoring `risk-v1.17.0`
**Date:** 2026-03-12
**Scope:** Data sources, pixel-level processing, spectral indices, feature derivation, urban detection, tidal zone classification, risk scoring. Infrastructure, routing, and persistence are excluded.

---

## Table of contents

1. [Data sources](#1-data-sources)
2. [Spatial footprint](#2-spatial-footprint)
3. [Scene selection](#3-scene-selection)
4. [Cloud and quality masking (SCL)](#4-cloud-and-quality-masking-scl)
5. [Sentinel-2 spectral indices](#5-sentinel-2-spectral-indices)
6. [Monthly aggregation](#6-monthly-aggregation)
7. [Long-term optical features and episode flags](#7-long-term-optical-features)
8. [Sentinel-1 SAR flood analysis](#8-sentinel-1-sar-flood-analysis)
9. [TerraClimate gridded climate features](#9-terraclimate-gridded-climate-features)
10. [Urban detection](#10-urban-detection)
11. [Tidal zone classification (NOAA CO-OPS)](#11-tidal-zone-classification)
12. [Elevation features (DTM: 3DEP / GLO-30)](#12-elevation-features)
13. [Risk scoring](#13-risk-scoring)
14. [Quality metadata](#14-quality-metadata)
15. [Known limitations and spectral confounds](#15-known-limitations-and-spectral-confounds)
16. [Parameter reference](#16-parameter-reference)

---

## 1. Data sources

### 1.1 Sentinel-2 L2A (optical)

| Attribute | Value |
|-----------|-------|
| Constellation | ESA Sentinel-2A + 2B |
| Product level | Level-2A (bottom-of-atmosphere reflectance, Sen2Cor atmospheric correction) |
| Revisit | ~5 days at equator; ~2-3 days with both satellites |
| Native resolution | 10 m (B02, B03, B04, B08); 20 m (B11, B12, SCL) |
| Archive | AWS Earth Search v1 (`earth-search.aws.element84.com/v1`) |
| Collection | `sentinel-2-l2a` |
| Storage | Public S3 COG (`sentinel-cogs`, us-west-2) |

Bands used:

| Band | Name | λ centre (nm) | Resolution | Role |
|------|------|--------------|-----------|------|
| B02 | Blue | 492 | 10 m | BSI |
| B03 | Green | 560 | 10 m | NDWI, NDSI |
| B04 | Red | 665 | 10 m | NDVI, BSI |
| B08 | NIR | 833 | 10 m | NDVI, NDWI, NDMI, NBR, BSI |
| B11 | SWIR1 | 1614 | 20 m | NDMI, NDSI, BSI |
| B12 | SWIR2 | 2202 | 20 m | NBR |
| SCL | Scene Classification | -- | 20 m | Pixel-level quality mask |

All bands are read as 16-bit unsigned integer digital numbers (DN). Reflectance values are obtained by dividing by 10,000 (ESA L2A convention). Index computations operate directly on reflectance values in [0, 1].

### 1.2 Sentinel-1 GRD (SAR)

| Attribute | Value |
|-----------|-------|
| Constellation | ESA Sentinel-1A + 1B |
| Mode | IW (Interferometric Wide Swath) |
| Product | GRD (Ground Range Detected) |
| Polarization used | VV (vertical transmit / vertical receive) |
| Revisit | ~6 days |
| Nominal pixel spacing | 10 m (true resolution ~20 m) |
| Archive | AWS Earth Search v1 |
| Collection | `sentinel-1-grd` |
| Storage | Public S3 (`sentinel-s1-l1c`, eu-central-1) |

GRD files contain radiometrically calibrated backscatter as uint16 DN. The approximate dB conversion is:

```
σ₀ (dB) ≈ 20 × log₁₀(DN) − 83
```

SAR penetrates clouds and operates day/night, providing flood-detection capability independent of optical conditions.

### 1.3 TerraClimate (monthly gridded climate)

| Attribute | Value |
|-----------|-------|
| Provider | University of Idaho Climatology Lab / Northwest Knowledge Network |
| Resolution | 1/24° (~4 km) global grid |
| Cadence | Monthly |
| Coverage | 1958 -- 2024 |
| Access | OPeNDAP point extraction via THREDDS server |

Variables extracted:

| Variable | Key | Physical unit | CF scale | CF offset |
|----------|-----|--------------|---------|----------|
| Max temperature | `tmax` | °C | 0.01 | −99.0 |
| Min temperature | `tmin` | °C | 0.01 | −99.0 |
| Precipitation | `ppt` | mm | 0.1 | 0.0 |
| Vapor pressure deficit | `vpd` | kPa | 0.01 | 0.0 |
| Palmer Drought Severity Index | `PDSI` | dimensionless | 0.01 | −45.0 |

Physical value = raw integer × scale + offset. Fill value: −32768 (Int16) / −2147483648 (Int32).

Grid cell centre coordinates are derived by:
```
lat_idx = round((89.979167 − lat) × 24)
lon_idx = round((lon + 179.979167) × 24)
grid_lat = 89.979167 − lat_idx / 24
grid_lon = lon_idx / 24 − 179.979167
```

---

### 1.4 Elevation DEM (hybrid: USGS 3DEP + Copernicus GLO-30)

Terrain features are read from a two-source priority chain. For US locations the USGS 3DEP 1" lidar-derived DTM is tried first; if the tile is missing or yields insufficient valid pixels, or for all non-US locations, the Copernicus GLO-30 DSM is used as the global fallback.

**USGS 3DEP 1" (primary, US only)**

| Attribute | Value |
|-----------|-------|
| Product | USGS 3D Elevation Program, 1 arc-second (~30 m), bare-earth lidar DTM |
| Source | Airborne lidar; removes vegetation canopy and building rooftops |
| Archive | AWS S3 `s3://prd-tnm/` (us-west-2), public, no authentication required |
| Tile grid | 1°×1° tiles, naming `StagedProducts/Elevation/1/TIFF/current/n{lat}w{lon}/USGS_1_n{lat}w{lon}.tif` |
| Coverage | Continental US, Alaska, Hawaii (lat 18--72°N, lon 180--64°W) |
| Cache | Same `elevation_cache` table; one read per location |

**Copernicus GLO-30 (fallback, global)**

| Attribute | Value |
|-----------|-------|
| Product | Copernicus Digital Elevation Model (GLO-30), 1 arc-second resolution (~30 m) |
| Source | TanDEM-X radar (DSM -- includes canopy and building heights); vertical accuracy ~1 m RMSE flat, ~2-4 m rugged |
| Archive | AWS S3 `s3://copernicus-dem-30m/` (eu-central-1), public, no authentication required |
| Tile grid | 1°×1° tiles, naming `Copernicus_DSM_COG_10_{N|S}{lat:02d}_00_{E|W}{lon:03d}_00_DEM/...tif` |
| Coverage | Global |
| Cache | Same `elevation_cache` table; one read per location |

### 1.5 NOAA CO-OPS (tidal stations and tide predictions)

| Attribute | Value |
|-----------|-------|
| Provider | NOAA Center for Operational Oceanographic Products and Services |
| Coverage | ~1,000 active US water-level tidal stations |
| Station metadata API | `mdapi/prod/webapi/stations.json?type=waterlevels` |
| Predictions API | `api/prod/datagetter` |
| Datum | MSL (Mean Sea Level): 0 = mean sea level, positive above, negative below |
| Interval | Hourly, UTC |
| Caching | Station list refreshed every 30 days; predictions cached permanently per (station, date) |

The station list is downloaded at application startup and stored in DuckDB. For each analysis location the service finds the nearest tidal station. If within `TIDAL_ZONE_RADIUS_KM` (default 30 km) the site is classified as a tidal zone.

For tidal zone sites, each Sentinel-1 SAR scene acquisition UTC time is parsed from the scene ID filename (`S1X_IW_GRDH_1SDV_YYYYMMDDTHHMMSS_...`). The NOAA predictions API is queried for hourly MSL values covering the acquisition date. The tide level at the exact acquisition minute is obtained by linear interpolation between the two bounding hourly values. Results are displayed in the HTML report below each SAR thumbnail and returned as `tide_level_m` in the `sar_scenes` array of the JSON report.

---

## 2. Spatial footprint

All analysis is performed over a fixed square window centred on the location centroid. For Point inputs, the centroid is the input coordinate. For Polygon inputs, it is the geometric centroid.

Window dimensions:

| Band class | Native pixel size | Window size | Ground footprint |
|-----------|-----------------|------------|----------------|
| 10 m bands (B02, B03, B04, B08) | 10 m | 64 × 64 px | 640 m × 640 m |
| 20 m bands (B11, B12, SCL) | 20 m | 32 × 32 px | 640 m × 640 m |

20 m bands are expanded to 64 × 64 by 2× pixel block repeat for array alignment before index computation. No interpolation is applied; each 20 m pixel maps to a 2 × 2 block of 10 m positions.

All reads use the scene's native UTM CRS. The WGS84 centroid is reprojected to UTM before window extraction.

---

## 3. Scene selection

### 3.1 Sentinel-2

1. STAC search for all items in `sentinel-2-l2a` intersecting the location bounding box over the analysis date window, with a server-side filter `eo:cloud_cover < 80` to avoid fetching scenes that will almost certainly fail the pixel-level mask test.
2. Group items by calendar month (`YYYY-MM`).
3. Within each month, sort by `eo:cloud_cover` (scene-level catalog metadata, ascending).
4. Keep up to `MAX_SCENES_PER_MONTH = 2` items per month.
5. Apply a hard cap of `MAX_TOTAL_SCENES = 120` across the full window (lowest-cloud months have priority).

The STAC search fetch budget (`STAC_MAX_ITEMS = 2000`) is deliberately decoupled from the processing cap. MPC returns items newest-first by default. If the fetch budget were set close to `MAX_TOTAL_SCENES`, dense-overpass areas (6-8 tiles per month) would exhaust the budget before reaching older months, silently truncating the analysis window to 2-3 years. The 2000-item budget provides comfortable headroom for 5 years at any global overpass density.

Default analysis window: `date_end − lookback_years` to `date_end`. Default `lookback_years = 5`.

### 3.2 Sentinel-1

1. STAC search for all items in `sentinel-1-grd` intersecting the bounding box over the analysis window.
2. Filter to IW mode, GRD product, with a VV asset present.
3. No cloud-cover sorting (SAR is cloud-independent).
4. Group by calendar month; within each month, select one representative scene per relative orbit (the first scene encountered for that orbit). This guarantees orbital diversity: look-angle-dependent backscatter bias is avoided without including redundant scenes from the same pass.
5. Keep up to `SAR_MAX_SCENES_PER_MONTH = 2` distinct orbits per month; hard cap `SAR_MAX_TOTAL_SCENES = 120`.

The relative orbit number (`sat:relative_orbit` STAC property, or derived from the absolute orbit and platform) identifies which ground track the scene was acquired from.

---

## 4. Cloud and quality masking (SCL)

Sentinel-2 L2A includes a Scene Classification Layer (SCL) at 20 m that classifies each pixel into one of 12 classes. The mask is applied at the pixel level before any index computation.

Valid (unmasked) SCL classes:

| SCL value | Label | Rationale for inclusion |
|-----------|-------|------------------------|
| 2 | Dark area pixels | Dark vegetation, shaded slopes, dark soils -- genuine land surface, not cloud |
| 4 | Vegetation | Core valid class |
| 5 | Not vegetated (bare soil, urban) | Core valid class |
| 6 | Water | Core valid class |
| 7 | Unclassified / low cloud probability | Low contamination risk; retains marginal scenes |
| 11 | Snow / Ice | Snow is a physical land surface; excluding it would blank alpine/high-latitude winter scenes and prevent NDSI computation |

All other classes (0 No data, 1 Defective, 3 Cloud shadow, 8 Cloud medium, 9 Cloud high, 10 Thin cirrus) are masked. Masked pixels are set to NaN before index computation.

**Scene rejection:** if fewer than `MIN_VALID_PIXEL_FRACTION = 5%` of the 64 × 64 window pixels survive the SCL mask, the entire scene is discarded. A scene producing fewer than 205 valid pixels out of 4,096 contributes no observations for that month. This threshold allows scenes with a small but usable clear window in otherwise cloudy conditions to contribute observations.

**Cloud fraction per scene:**

```
cloud_fraction = (total_pixels − valid_pixels) / total_pixels
```

---

## 5. Sentinel-2 spectral indices

All indices are computed pixel-by-pixel across the 64 × 64 array over reflectance values in [0, 1]. Division by zero (sum of bands = 0) produces NaN, not an error. The spatial mean across valid (non-NaN) pixels is the observation value for that scene.

### 5.1 NDVI -- Normalized Difference Vegetation Index

```
NDVI = (B08 − B04) / (B08 + B04)
```

Range: [−1, +1]. Healthy dense vegetation: 0.6 -- 0.9. Sparse vegetation: 0.2 -- 0.4. Bare soil, urban impervious: < 0.1. Water, snow, cloud shadow: typically < 0.

Reference: Rouse et al. (1974).

### 5.2 NDWI -- Normalized Difference Water Index

```
NDWI = (B03 − B08) / (B03 + B08)
```

McFeeters (1996) formulation. Range: [−1, +1]. Open water reflects green strongly and absorbs NIR: positive values. Vegetation and soil: negative values. Threshold for surface water presence: NDWI > 0 (configurable via `NDWI_WET_THRESHOLD`).

This formulation is locked in processing version `s2l2a-v1.1.0`. It targets open surface water bodies. It is **not** the Gao (1996) vegetation moisture formulation, which uses NIR and SWIR; that sensitivity is covered by NDMI.

### 5.3 NDMI -- Normalized Difference Moisture Index

```
NDMI = (B08 − B11) / (B08 + B11)
```

Range: [−1, +1]. Measures leaf and canopy water content using NIR and SWIR1. Positive values indicate good moisture status. Values below 0 indicate vegetation moisture stress (`NDMI_STRESS_THRESHOLD = 0.0`).

Reference: Gao (1996), Wilson & Sader (2002).

### 5.4 NBR -- Normalized Burn Ratio

```
NBR = (B08 − B12) / (B08 + B12)
```

Range: [−1, +1]. Healthy unburned vegetation has high NIR and low SWIR2 (NBR > 0.3). Post-fire areas lose chlorophyll (NIR decreases) and expose char/soil (SWIR2 increases), driving NBR toward negative values. An absolute value of NBR < 0.1 (`NBR_BURN_THRESHOLD`) is used for chart bar colour annotation. Fire detection and SAR burn suppression use an anomaly-based approach (see section 7.4): a month is flagged only when NBR drops more than `NBR_ANOMALY_THRESHOLD` below the site's own seasonal climatology.

Reference: Key & Benson (1999).

### 5.5 NDSI -- Normalized Difference Snow Index

```
NDSI = (B03 − B11) / (B03 + B11)
```

Range: [−1, +1]. Snow has very high reflectance in visible green and near-zero reflectance in SWIR1. Threshold for snow cover: NDSI > 0.4 (`NDSI_SNOW_THRESHOLD`).

Reference: Hall et al. (1995).

### 5.6 BSI -- Bare Soil Index

```
BSI = (B11 + B04 − B08 − B02) / (B11 + B04 + B08 + B02)
```

Range: [−1, +1]. SWIR1 and Red highlight bare soil; NIR suppresses vegetation signal; Blue suppresses shadow. Positive values indicate exposed bare/impervious surfaces. Threshold: BSI > 0 (`BSI_BARE_THRESHOLD`).

Reference: Rikimaru et al. (2002).

---

## 6. Monthly aggregation

For each month with one or more valid scenes, a weighted mean is computed across all scenes that passed the SCL mask test:

```
monthly_mean = Σ (mean_i × valid_pixel_count_i) / Σ valid_pixel_count_i
```

where `mean_i` is the spatial mean of the index over valid pixels in scene `i`, and `valid_pixel_count_i` is the number of valid pixels in that scene. This weights scenes with better coverage more heavily.

A month is marked as not observed (`mean = None`) if all its scenes were rejected (insufficient valid pixels). Not-observed months are excluded from all subsequent feature computations.

---

## 7. Long-term optical features

All features are computed from the full monthly time series over the analysis window (default 5 years). The suffix `_5y` in feature names reflects the default lookback; the actual window length is determined by the request parameters.

### 7.1 NDVI features

**`ndvi_mean_5y`** -- Arithmetic mean of all valid monthly NDVI values.

**`ndvi_trend_slope_5y`** -- Theil-Sen robust linear regression slope over the monthly series, expressed in NDVI units per year. Month indices (0, 1, ..., N−1) are used as the x-axis; the per-month slope is multiplied by 12 to convert to per-year. Minimum 6 valid observations required; returns None otherwise. A negative slope indicates long-term vegetation decline.

Theil-Sen estimator: the slope is the median of all pairwise slopes `(y_j − y_i) / (x_j − x_i)` for all pairs `i < j`. This estimator is unbiased under 50% data corruption and is preferred over OLS for remotely sensed time series with outliers.

**`ndvi_anomaly_freq_5y`** -- Fraction of observed months where NDVI is more than 0.1 units below the climatological mean for that calendar month:

```
For each observed month (year y, calendar month m):
    climatology[m] = mean of all NDVI values for calendar month m across all years
    anomaly = True  iff  NDVI[y,m] < climatology[m] − 0.1
ndvi_anomaly_freq_5y = count(anomaly == True) / count(observed months)
```

This removes the seasonal cycle before flagging deficit months. The threshold of −0.1 NDVI units was selected to suppress noise while catching genuine drought or disturbance responses.

### 7.2 NDWI features

**`ndwi_wetness_persistence_5y`** -- Fraction of observed months where monthly mean NDWI > 0:

```
ndwi_wetness_persistence_5y = count(NDWI_monthly > 0) / count(observed months)
```

High values indicate persistent surface water (wetlands, riparian zones, tidal flats).

**`ndwi_trend_slope_5y`** -- Theil-Sen slope of monthly NDWI values, in index units per year. Minimum 6 valid observations required. A positive slope indicates a wetter trajectory; negative indicates drying. Used as a supplementary component in `wetness_score` (section 13.2).

### 7.3 NDMI features

**`ndmi_mean_5y`** -- Mean of all valid monthly NDMI values.

**`ndmi_moisture_stress_freq_5y`** -- Fraction of months where NDMI < 0:

```
ndmi_moisture_stress_freq_5y = count(NDMI_monthly < 0) / count(observed months)
```

**`ndmi_trend_slope_5y`** -- Theil-Sen slope of monthly NDMI values, in index units per year. A negative slope indicates a worsening moisture stress trend. Used as a supplementary drought component in `drought_score` (section 13.1).

**`ndmi_momentum_ratio_1y`** -- See section 7.10.

### 7.4 NBR features

**`nbr_mean_5y`** -- Mean of all valid monthly NBR values.

**`nbr_burn_freq_5y`** -- Fraction of observed months where NBR drops anomalously below the site's own seasonal climatology, in runs of at least `NBR_MIN_CONSECUTIVE` calendar-consecutive months:

```
For each observed month (year y, calendar month m):
    climatology[m] = mean of all NBR values for calendar month m across all years
    fire_anomaly   = True  iff  NBR[y,m] < climatology[m] − NBR_ANOMALY_THRESHOLD (0.15)

Qualifying months: those belonging to a run of ≥ NBR_MIN_CONSECUTIVE (default 3) calendar-
consecutive anomaly observations. A gap in the observation record breaks the run.

nbr_burn_freq_5y = count(qualifying months) / count(observed months)
```

This is the same anomaly-based methodology as `ndvi_anomaly_freq_5y`. The seasonal cycle is removed before thresholding, so persistent low NBR that is normal for the site -- dormant grassland, harvested cropland, semi-arid prairie, sparse boreal understorey -- is not flagged. Only abrupt departures from the site's own seasonal norm are counted.

The consecutive-month requirement filters isolated single-month dips caused by agricultural harvest or a brief drought response, which are spectrally indistinguishable from fire by amplitude alone. Genuine fire events produce burn scars that suppress NBR for multiple consecutive months during post-fire recovery.

The distinction matters in practice: a post-fire chaparral site (Pacific Palisades) shows a sudden drop of ~0.6 NBR units below its pre-fire seasonal mean, sustained for 3+ months -- always caught. A Mediterranean site (Cape Town fynbos) has naturally low absolute NBR in the summer dry season; because the site's own summer climatology already expects these values, the anomaly is near zero regardless of the consecutive count, and no fire event is detected. A continental prairie site (Calgary) has consistently low NBR in autumn for the same reason: zero anomaly relative to seasonal norm.

Note: `NBR_BURN_THRESHOLD` (absolute, 0.1) is retained for chart bar colour annotation only. All fire detection and SAR burn suppression use `NBR_ANOMALY_THRESHOLD` + `NBR_MIN_CONSECUTIVE`.

**`nbr_momentum_ratio_1y`** -- Ratio of fire-anomaly frequency in the last 12 months vs the 5-year baseline, using the same anomaly definition as `nbr_burn_freq_5y` (NBR drops > `NBR_ANOMALY_THRESHOLD` below seasonal climatology). Computed by the same `compute_recent_anomaly_ratio` function as the optical momentum features (section 7.10). Returns `None` when `nbr_burn_freq_5y < 0.01` (no historical fire signal to compare against) or when fewer than 3 recent observations exist. A ratio > 1.0 means fire anomaly frequency is accelerating relative to the 5-year norm and amplifies the fire exposure score (section 13.3).

### 7.5 NDSI features

**`ndsi_snow_persistence_5y`** -- Fraction of months where NDSI > 0.4:

```
ndsi_snow_persistence_5y = count(NDSI_monthly > 0.4) / count(observed months)
```

### 7.6 BSI features

**`bsi_mean_5y`** -- Mean of all valid monthly BSI values.

**`bsi_bare_soil_freq_5y`** -- Fraction of months where BSI > 0:

```
bsi_bare_soil_freq_5y = count(BSI_monthly > 0) / count(observed months)
```

BSI frequency is used (rather than BSI mean) for urban detection because snow on impervious surfaces produces negative BSI, which would dilute the annual mean. Frequency over the snow-inclusive SCL class set is robust to this effect.

Also for section 7.1: **`ndvi_momentum_ratio_1y`** -- See section 7.10.

### 7.7 Canopy proxy

**`canopy_proxy`** -- Mean peak-season NDVI across years, serving as a proxy for canopy cover density:

```
For each year y:
    peak_y = max(NDVI_monthly[y,m]  for m in growing_season_months
                 if NDVI_monthly[y,m] is not None)
canopy_proxy = mean(peak_y for all years with at least one growing-season observation)
```

Growing season definition (Köppen zone + hemisphere):

| Köppen zone | NH months | SH months |
|-------------|-----------|-----------|
| Tropical (A) | Jan -- Dec (full year) | Jan -- Dec |
| Arid (B) | Jan -- Dec (full year) | Jan -- Dec |
| Mediterranean (Cs) | Mar -- Jun (spring, before drought) | Sep -- Dec |
| Temperate / Continental (C non-Cs, D), ≥ 33° abs lat | May -- Sep | Nov -- Mar |
| Temperate / Continental, < 33° abs lat | Mar -- Nov | Sep -- May |
| Polar / Alpine (E) | Jun -- Aug | Dec -- Feb |

SH months are the NH months shifted by 6 calendar months. Köppen code is looked up from the 0.5° gridded climatology stored at location creation time.

The canopy proxy approximates canopy closure from the peak photosynthetic signal rather than mean NDVI, which is suppressed in winter. It is used in heat mitigation scoring and urban detection.

### 7.10 Recent anomaly ratios (1y momentum)

Five features quantify whether the most recent 12 months are anomalous more or less often than the 5-year baseline. The ratio > 1.0 means conditions are worsening; < 1.0 means improving. Capped at 5.0.

**For optical indices (`ndvi_momentum_ratio_1y`, `ndmi_momentum_ratio_1y`, `nbr_momentum_ratio_1y`):**

```
sorted_valid = all valid monthly records sorted chronologically

For each record r:
    climatology[cal_month] = mean of all values for that calendar month
    is_anomaly(r) = True iff r.mean < climatology[r.cal_month] - threshold

baseline_freq  = count(is_anomaly) / count(sorted_valid)
recent_recs    = records where 0 ≤ (end_abs − record_abs) < 12 months
recent_freq    = count(is_anomaly in recent_recs) / count(recent_recs)

momentum_ratio = min(recent_freq / baseline_freq, 5.0)
```

Returns `None` when `baseline_freq < 0.01` (no historical anomalies to compare against) or when fewer than 3 observations exist in the recent window. For `ndvi_momentum_ratio_1y` and `ndmi_momentum_ratio_1y`, threshold is `NDVI_ANOMALY_THRESHOLD` (0.1 index units below seasonal mean). For `nbr_momentum_ratio_1y`, threshold is `NBR_ANOMALY_THRESHOLD` (0.15 index units below seasonal mean).

**For TerraClimate variables (`tmax_momentum_ratio_1y`, `pdsi_momentum_ratio_1y`):**

The same ratio logic applies but uses absolute thresholds rather than climatology-relative departure:

- `tmax_momentum_ratio_1y`: anomaly defined as `tmax > climatology_mean[m] + σ × std[m]` (same as `tmax_anomaly_freq_5y`)
- `pdsi_momentum_ratio_1y`: anomaly defined as `PDSI < -2.0` (same threshold as `pdsi_drought_freq_5y`)

These features act as scaling amplifiers in risk scoring (section 13.6) and are recomputed from already-cached monthly timeseries -- no additional satellite fetching is required.

### 7.8 Active episode flags

Three binary features (0.0 / 1.0) indicate whether a climate episode is ongoing near the analysis end date. They are recomputed each time the pipeline runs; the threshold logic is intentionally conservative (short recency window, confirmed signals only) to avoid spurious alerts.

**`active_flood`**

```
active_flood = 1.0  iff  sar_flood_anomaly > 0.10
              AND  at least one corroboration condition is true:
                     ndwi_wetness_persistence_5y > SAR_ACTIVE_FLOOD_MIN_NDWI (0.08)
                     OR sar_flood_anomaly > SAR_ACTIVE_FLOOD_STRONG_ANOMALY (0.35)
```

`sar_flood_anomaly` already covers only the most recent two calendar months of SAR scenes (see §8.6). A value above 10% means SAR water fraction is elevated by at least 10 percentage points above the orbit-stratified seasonal baseline in at least one recent pass.

**Corroboration requirement:** A SAR anomaly alone is not sufficient to trigger the flag. SAR backscatter depends heavily on look angle: a single orbit viewing a snow-covered or rocky slope at the right incidence angle produces low-backscatter returns indistinguishable from open water. If both the acute anomaly and the chronic water frequency are driven by the same orbit artifact, using one to corroborate the other is circular. Corroboration therefore requires independent evidence:

1. **NDWI optical history** (`ndwi_wetness_persistence_5y > 0.08`): surface water appeared in optical data in at least ~1 month per year over the full window. Optical and SAR artifacts are uncorrelated, so this is a genuinely independent signal.
2. **Very strong anomaly** (`sar_flood_anomaly > 0.35`): a major event override -- catastrophic inundation, burst levees, or large-scale storm surge produces anomalies well above 35% regardless of background conditions.

`sar_water_freq_5y` is intentionally excluded from this list: in mountain valleys and arid terrain with relief, a single orbit consistently records low backscatter from the same slope geometry. That chronic signal then appears to corroborate the acute anomaly when both share the same artifact source.

Sites that fail both checks (typically: mountain valley terrain where one SAR orbit sees a snow/rock slope, high-altitude rocky terrain, or arid barren land) are not flagged as actively flooded even when the anomaly threshold is met.

**`active_fire`**

```
active_fire = 1.0  iff  any burn_month mk satisfies:
    (year(date_end) × 12 + month(date_end)) − (year(mk) × 12 + month(mk)) ≤ 3
```

`burn_months` is the set of consecutive-confirmed NBR anomaly months produced by `get_persistent_burn_months()` (same algorithm as `nbr_burn_freq_5y`). The 3-month recency window is wide enough to catch post-fire NBR suppression during early recovery, which typically persists 2-6 months after the burn event.

**`active_drought`**

```
For each of the last 3 observed NDVI months before date_end
    (excluding snow months and persistently wet sites -- see suppression guards below):
    anomaly = True  iff  NDVI[y,m] < climatology[m] − NDVI_ANOMALY_THRESHOLD (0.1)
active_drought = 1.0  iff  at least 2 of these months are anomalous
```

The seasonal climatology is the **median** NDVI for each calendar month across the full analysis window (computed with `_median()`). Using the median rather than the mean makes the baseline robust to exceptional wet or dry years: a single anomalous year does not inflate (or deflate) the reference climatology for that month.

At least **2 of the 3** recent months must be anomalously low to set the flag (raised from any 1/3). A single anomalous month can arise from cloud contamination or partial sensor dropout that passed the SCL quality mask. Requiring 2 consecutive-or-concurrent anomalous months suppresses these one-off false positives while still detecting rapid drought onset.

**Suppression guards:** NDVI is a vegetation health proxy and is only meaningful as a drought indicator on vegetated land. Two land cover conditions produce near-zero or negative NDVI that is spectrally indistinguishable from drought stress but has a different physical cause:

1. **Snow cover:** Snow reflects nearly equally in Red and NIR, collapsing NDVI to near zero. Months where co-located NDSI > `NDSI_SNOW_THRESHOLD` (0.4) are excluded from the recency window before the anomaly check. This mirrors the SAR snow suppression logic.

2. **Tidal zone sites (NOAA CO-OPS proximity):** A site classified as tidal zone (`is_tidal_zone = 1.0`) is permanently inundated or strongly influenced by tidal dynamics. NDVI at these locations reflects emergent vegetation senescence and water surface exposure driven by tidal cycles, not atmospheric moisture deficit. `active_drought` is suppressed unconditionally for all tidal zone sites. This replaces the prior empirical SAR/NDWI thresholds as the primary suppression mechanism for coastal inundation.

3. **Persistently wet non-tidal sites (marshes, inland wetlands):** Sites not in the NOAA tidal database but where remote sensing signals consistently indicate permanent or near-permanent water. The drought flag is suppressed when:
   ```
   sar_water_freq_5y > 0.70   (SAR confirms near-permanent surface water)
   OR ndwi_wetness_persistence_5y > 0.30  (optical confirms frequent surface water)
   ```
   These thresholds identify sites where NDVI is governed by water surface dynamics rather than vegetation stress.

### 7.9 Quality score

**`quality_score`** -- Composite data quality indicator in [0, 1]:

```
coverage  = months_observed / months_total
clarity   = 1 − mean_cloud_fraction

quality_score = 0.65 × coverage + 0.35 × clarity
```

Temporal coverage is weighted more heavily (65%) because missing months directly affect the reliability of trend and anomaly features. Scene clarity (35%) captures residual cloud contamination within accepted scenes.

`mean_cloud_fraction` is computed only over months that have at least one valid observation, so that fully-cloudy months (which already reduce `coverage`) do not also inflate the cloud fraction estimate.

---

## 8. Sentinel-1 SAR flood analysis

### 8.1 Water detection at the scene level

For each S1 GRD scene, the VV backscatter array (64 × 64 pixels, uint16 DN) is read via rasterio WarpedVRT (required because raw ESA GRD files use GCP-based geolocation rather than a standard affine transform). The water fraction of a scene is:

```
valid_pixels = pixels where DN > 0  (DN = 0 is nodata)
              AND slope_deg < DEM_FLAT_SLOPE_THRESHOLD  (see §8.2)
water_pixels = pixels where 0 < DN < SAR_WATER_DN_THRESHOLD (75 DN)
              AND slope_deg < DEM_FLAT_SLOPE_THRESHOLD
water_fraction = water_pixels / valid_pixels
```

The 75 DN threshold was empirically calibrated against known reference sites:

| Surface type | DN range | σ₀ (approx dB) |
|-------------|---------|----------------|
| Thermal noise floor | ~35 DN | ~−52 dB |
| Calm open water (specular) | 35 -- 70 DN | −52 to −45 dB |
| Vegetated land | 100 -- 250 DN | −43 to −37 dB |
| Land mean (observed) | ~141 DN | ~−40 dB |
| Urban / corner reflectors | ≥ 500 DN | ≥ −30 dB |

Open water acts as a specular reflector: VV microwave energy scatters away from the sensor, yielding very low backscatter. The 75 DN threshold sits between the water range (35 -- 70 DN) and the land mean (141 DN), providing a margin above the noise floor.

**DEM slope mask (`DEM_FLAT_SLOPE_THRESHOLD = 15°`):** SAR C-band backscatter is strongly look-angle dependent. On steep slopes, the radar energy can be directed away from the sensor in a geometry that mimics calm open water, even over rocky or snow-covered terrain. To avoid counting these geometric artefacts as water pixels, the valid pixel set is restricted to pixels where the DEM-derived slope is below 15°. Both the numerator (water pixels) and denominator (valid pixels) exclude steep-slope pixels before the fraction is computed.

The slope is derived from the cached 64 × 64 elevation array (same window as the SAR read) using `numpy.gradient` with the 10 m effective pixel spacing. The DEM pipeline runs concurrently with the SAR pipeline; the elevation array is guaranteed to be in the database before the water fractions are recomputed. If the elevation array is unavailable (e.g. DEM tile missing for a remote location), no masking is applied and water fractions fall back to the unmasked computation.

This correction has no effect on flat terrain (slope uniformly below threshold) and reduces inflated fractions in mountain valley and alpine locations where a single SAR orbit has a look angle that persistently views a slope face.

### 8.2 Snow suppression

SAR scenes from months where co-located S2 NDSI > 0.4 are excluded from the chronic water frequency computation. Compact dry snow and smooth ice are also specular reflectors with low VV backscatter, producing false water signatures spectrally indistinguishable from calm open water. This suppression is applied **only to the chronic frequency** (`sar_water_freq_5y`), not to the flood anomaly metric.

### 8.3 Burn suppression

SAR scenes from months that belong to a confirmed fire event are excluded from both the chronic frequency and the flood anomaly computation. Post-fire bare soil and ash exhibit low VV backscatter that can fall below the 75 DN water threshold, producing false flood detections.

Fire events are identified using the same anomaly-based, consecutive-month algorithm as `nbr_burn_freq_5y` (section 7.4): a month is suppressed only if it belongs to a run of ≥ `NBR_MIN_CONSECUTIVE` calendar-consecutive months where NBR drops more than `NBR_ANOMALY_THRESHOLD` below the site's own seasonal climatology. This is climate-zone aware: Mediterranean dry seasons (Cape Town fynbos, California chaparral pre-fire) have near-zero NBR anomaly relative to the site climatology and are never suppressed, even when absolute NBR values are low. Post-fire months show an abrupt departure well below the pre-fire seasonal norm and are correctly suppressed.

The burn suppression is applied to both the chronic and the acute metrics because (unlike the snow case) there is no risk of suppressing genuine flood events: a flood and a fire cannot be simultaneously responsible for low backscatter at the same pixel in the same month.

Residual risk: if the optical SCL mask discards the S2 scene for the same month (e.g. due to wildfire smoke), NBR is not available and burn suppression cannot be applied.

### 8.4 Orbit stratification

Sentinel-1 VV backscatter depends on incidence angle and look direction, both of which vary between orbital passes (relative orbit numbers). Mixing scenes from different relative orbits in a single frequency calculation inflates variance and distorts anomaly detection. Scenes are stratified by relative orbit; frequency is computed per orbit track and the maximum across tracks is reported:

```
sar_water_freq_5y = max over all orbits of: orbit_frequency(orbit_scenes)
```

### 8.5 Chronic water frequency (`sar_water_freq_5y`)

Input: post-suppression scenes `(month_key, water_fraction, relative_orbit)`.

For each orbit, two thresholds are evaluated and the higher resulting frequency is retained:

**Absolute threshold:**
```
absolute_freq = count(water_fraction > 0.35) / N_orbit_scenes
```
No consecutive-scene requirement: permanently wet sites (lakes, coastal bays) have real water by definition.

**Adaptive (MAD-based) threshold:**
```
loc_median = median(water_fraction for orbit scenes)
MAD = median(|water_fraction_i − loc_median|)
adaptive_threshold = max(loc_median + 2.0 × MAD,  0.05)
elevated = [water_fraction > adaptive_threshold for each scene, sorted by month]
```

Anomalous scenes are counted only when they belong to a run of at least `SAR_MIN_CONSECUTIVE_FLOOD_MONTHS = 2` calendar-consecutive months (i.e., months that are exactly one calendar month apart, handling year boundaries correctly). Single-month spikes from wind roughening, a brief specular glint, or instrument artefacts are discarded; genuine multi-pass flood events spanning 2+ months are preserved.

```
anomaly_freq = count(qualifying elevated scenes) / N_orbit_scenes
orbit_frequency = max(absolute_freq, anomaly_freq)
```

The adaptive threshold uses the Median Absolute Deviation (MAD) rather than standard deviation because MAD is not inflated by the flood outliers it is designed to detect (unlike σ, which increases when extreme values are present, raising the detection bar exactly when sensitivity is needed). The 0.05 floor prevents statistical leakage: at very stable low-water orbits, the MAD approaches zero and even trivial instrument noise would otherwise exceed `median + k × MAD`.

The absolute threshold (0.35) independently handles chronically wet locations (lakes, coastal bays, tidal flats) where the baseline water fraction is already elevated and the adaptive threshold would require an anomaly above an already-high median.

### 8.6 Acute flood anomaly (`sar_flood_anomaly`)

Input: **all** SAR scenes `(month_key, water_fraction, relative_orbit)` including snow months but excluding burn months. Snow suppression is deliberately omitted here: flooded agricultural fields also exhibit NDSI-like spectral signatures under certain conditions, and the anomaly comparison is relative (recent vs. historical), not absolute, reducing noise sensitivity.

The baseline is orbit-stratified: each recent scene is compared to the historical median for the same (relative orbit, calendar month) pair. This removes look-angle-dependent backscatter bias from the comparison. When insufficient historical data exists for the exact (orbit, cal_month) pair (fewer than 2 scenes), the computation falls back to a combined baseline of all orbits for that calendar month.

```
recent_month_keys = {last 2 calendar months of the analysis window}

historical[(orbit, cal_month)] = [water_fraction for all scenes NOT in recent_month_keys]
historical[(0,     cal_month)] = same, orbit-agnostic fallback

For each recent scene (orbit, cal_month m, water_fraction w):
    hist = historical[(orbit, m)]
    if len(hist) < 2:
        hist = historical[(0, m)]  # fallback to orbit-agnostic baseline
    if len(hist) >= 2:
        baseline = median(hist)
        anomaly = max(0,  w − baseline)

sar_flood_anomaly = max(anomalies)  [clamped to [0, 1]]
```

This detects sudden increases in water coverage relative to the historical seasonal norm for the same calendar months and orbital pass, identifying acute flood events that may not accumulate to a significant chronic frequency.

---

## 9. TerraClimate gridded climate features

TerraClimate monthly series are fetched via OPeNDAP point extraction for the grid cell containing the location centroid. All years within the analysis window are requested. Features are derived from the resulting monthly time series.

### 9.1 Temperature features

**`tmax_mean_5y`** -- Mean of all valid monthly maximum temperature values (°C).

**`tmin_mean_5y`** -- Mean of all valid monthly minimum temperature values (°C).

**`tmax_summer_mean_5y`** -- Mean of monthly tmax restricted to growing-season months (same Köppen zone + hemisphere definition as canopy proxy; see section 7.7).

**`tmax_anomaly_freq_5y`** -- Fraction of months where tmax exceeds the monthly climatological mean by more than 1 standard deviation:

```
For each calendar month m (1--12):
    climatology_mean[m] = mean(tmax for all observations of month m)
    climatology_std[m]  = stdev(tmax for all observations of month m)

tmax_anomaly_freq_5y = count(tmax[y,m] > climatology_mean[m] + σ × climatology_std[m])
                       / count(valid observations)
```

where σ = `TERRACLIMATE_TMAX_ANOMALY_SIGMA = 1.0`. Minimum 6 valid observations required.

**`tmax_trend_slope_5y`** -- Theil-Sen slope of monthly tmax, in °C per year (same method as NDVI trend). Minimum 12 valid observations required.

### 9.2 Precipitation features

**`ppt_annual_mean_5y`** -- Mean annual precipitation in mm, computed from yearly totals:

```
annual_total[y] = sum of monthly ppt for year y (included only if ≥ 10 months present)
ppt_annual_mean_5y = mean(annual_total[y] for all years)
```

### 9.3 Vapor pressure deficit features

**`vpd_mean_5y`** -- Mean of all valid monthly VPD values (kPa).

**`vpd_high_freq_5y`** -- Fraction of months where VPD > 1.5 kPa (`TERRACLIMATE_VPD_HIGH_THRESHOLD`):

```
vpd_high_freq_5y = count(vpd_monthly > 1.5) / count(valid months)
```

VPD above ~1.5 kPa induces significant stomatal closure in most vegetation types and is associated with elevated wildfire risk in Mediterranean and arid climates.

**`vpd_trend_slope_5y`** -- Theil-Sen slope of monthly VPD, in kPa per year. Minimum 12 valid observations required. A rising trend indicates increasing atmospheric moisture demand. Used as a supplementary heat stress component in `heat_stress_score` (section 13.5).

### 9.4 PDSI features

**`pdsi_mean_5y`** -- Mean PDSI over the analysis window. PDSI > 0 = wetter than normal; PDSI < 0 = drier; PDSI < −2 = moderate drought; PDSI < −4 = extreme drought (Palmer 1965 classification).

**`pdsi_drought_freq_5y`** -- Fraction of months where PDSI < −2.0 (`TERRACLIMATE_PDSI_DROUGHT_THRESHOLD`):

```
pdsi_drought_freq_5y = count(PDSI_monthly < -2.0) / count(valid months)
```

**`pdsi_trend_slope_5y`** -- Theil-Sen slope of monthly PDSI, in index units per year. A negative slope indicates worsening drought conditions over the analysis window. Used as a supplementary drought component in `drought_score` (section 13.1).

**`pdsi_momentum_ratio_1y`** -- Ratio of PDSI drought frequency (PDSI < −2) in the last 12 months vs. the 5-year baseline. Computed using the same ratio method as the optical momentum features (section 7.10) but with the absolute drought threshold rather than a climatology-relative departure. Returns None when `pdsi_drought_freq_5y < 0.01` or when fewer than 3 recent observations are available.

---

## 10. Urban detection

Urban classification is determined by a two-path OR logic gate applied to the optical features, preceded by a barren-terrain guard:

**Barren terrain guard (applied before both paths):**
```
if ndvi_mean_5y < URBAN_MIN_NDVI_THRESHOLD (0.12):
    is_urban = False  (naturally barren -- desert, alpine rock, bare soil)
```
Near-zero 5-year mean NDVI indicates an absence of vegetation, not the presence of impervious surfaces. Every urban environment -- including those in arid climates with irrigated street trees and parks -- maintains enough mixed vegetation in a 640 m window to keep the 5-year mean above 0.12. Values below this threshold reliably indicate naturally barren terrain such as high-altitude rocky plateaus, desert reg, or exposed scree, where high BSI frequency reflects bare mineral substrate rather than concrete or asphalt. Both detection paths are suppressed when this guard fires.

**Path 1 (strong BSI signal alone):**
```
is_urban = True  if  bsi_bare_soil_freq_5y > 0.65
```
Captures tropical and subtropical cities (e.g. Miami, Houston) where year-round vegetation mixed with impervious surfaces keeps NDVI elevated, but the high frequency of bare/impervious signals in BSI still exceeds the threshold.

**Path 2 (combined signal):**
```
is_urban = True  if  bsi_bare_soil_freq_5y > 0.50
                AND  ndvi_mean_5y < 0.25
                AND  (canopy_proxy is None  OR  canopy_proxy < 0.25)
```
Captures dense temperate urban cores (e.g. Boston, Chicago) with low NDVI, low canopy, and persistent impervious signals.

Both paths evaluate to False (non-urban) if `bsi_bare_soil_freq_5y` is not available.

Urban classification has the following downstream effects:
- `drought_score` is forced to 0 (impervious surfaces have no vegetation drought signal)
- `fire_exposure_score` is forced to 0 (NBR on concrete/asphalt spectrally mimics burned vegetation; see section 13.1)
- The composite score uses a fixed urban weighting profile (section 11.6)

---

## 11. Tidal zone classification

### 11.1 Station proximity lookup

On startup the service downloads the NOAA CO-OPS water-level station list and stores it in DuckDB (`noaa_tidal_stations` table). For each analysis location the nearest station is found using the haversine formula:

```
distance_km = 6371 × 2 × arcsin(√(sin²(Δlat/2) + cos(lat1)×cos(lat2)×sin²(Δlon/2)))
```

A location is classified as **tidal zone** (`is_tidal_zone = 1.0`) when both conditions are met:

1. `distance_km ≤ TIDAL_ZONE_RADIUS_KM` (default 30 km)
2. `elevation_m ≤ TIDAL_ZONE_MAX_ELEV_M` (default 10 m)

The distance to the nearest station is stored as `nearest_tidal_station_km`.

The 30 km radius is calibrated to reliably capture tidal flats, coastal marshes, estuaries, and barrier island environments without over-reaching into purely inland areas. US coastal geography means that a 30 km inland buffer from any tidal station still encompasses most tidal influence zones.

The elevation gate (10 m MSL) addresses a physical impossibility: tidal dynamics cannot reach locations elevated well above mean sea level even when a NOAA station is geographically nearby. Without this gate, hillside and upland locations (e.g. a site at 140 m elevation near a coastal station) would be incorrectly classified as tidal, suppressing `active_drought` for locations where drought is a genuine risk. The 10 m threshold aligns with the upper bound of typical storm surge inundation for US Atlantic and Gulf Coast environments, above which tidal influence is negligible.

### 11.2 Effect on feature computation

Classification as a tidal zone immediately suppresses `active_drought` (section 7.5). This is the primary use of the tidal zone flag: NDVI anomalies at persistently inundated coastal sites reflect tidal water dynamics, not atmospheric drought, and should not trigger the drought episode badge.

Tidal zone classification is independent of the SAR and NDWI wet-site heuristics (SAR water freq > 0.70, NDWI persistence > 0.30), which remain as fallback suppressors for inland wetlands and marshes not captured by the NOAA station network.

### 11.3 SAR tide cross-reference

For tidal zone sites, each Sentinel-1 SAR scene is annotated with the NOAA predicted MSL tide level at the exact acquisition time (UTC). Scene IDs encode the acquisition start timestamp (`YYYYMMDDTHHMMSS` at position 4 in the `_`-delimited filename). The hourly predictions for the nearest station and acquisition date are fetched from NOAA and cached in DuckDB (`noaa_tide_predictions` table). The tide level at the acquisition minute is obtained by linear interpolation between the two bounding hourly values.

This cross-reference allows visual validation that SAR-detected water fraction follows the expected tidal cycle: scenes acquired near high tide should show higher water fractions than scenes acquired at low tide for the same location.

**Output fields added for tidal zone sites:**

| Field | Location | Description |
|-------|----------|-------------|
| `is_tidal_zone` | `features` | 1.0 for tidal zone, 0.0 otherwise |
| `nearest_tidal_station_km` | `features` | Distance to nearest NOAA station (km), null if none within radius |
| `tidal_zone` | `quality.flags` | Set when `is_tidal_zone == 1.0` |
| `tide_level_m` | `sar_scenes[*]` in report.json | MSL tide at SAR acquisition time (m); null for non-tidal sites |
| `nearest_tidal_station` | report.json top level | `{ station_id, name, lat, lon, tide_type, state, distance_km }` |

---

## 12. Elevation features

### 12.1 Data access

A single 64×64 pixel window (640m × 640m footprint) is read from the best available bare-earth DEM tile for the location centroid. For US locations (lat 18--72°N, lon 180--64°W) the USGS 3DEP 1" lidar DTM (`prd-tnm`, us-west-2) is tried first; on tile failure or insufficient valid pixels, or for all non-US locations, the Copernicus GLO-30 DSM (`copernicus-dem-30m`, eu-central-1) is used as the global fallback. Both sources use rasterio with anonymous S3 access (`AWS_NO_SIGN_REQUEST=YES`) and bilinear resampling. If fewer than 25% of pixels contain valid data (e.g. tile edge, ocean), the result is discarded and the `no_dem_data` quality flag is set.

### 12.2 Derived features

| Feature | Formula | Unit |
|---------|---------|------|
| `elevation_m` | `nanmean(window)` | metres (WGS84 ellipsoidal) |
| `elevation_min_m` | `nanmin(window)` | metres |
| `elevation_max_m` | `nanmax(window)` | metres |
| `elevation_range_m` | `elevation_max_m − elevation_min_m` | metres |
| `slope_deg` | `mean(degrees(arctan(sqrt(dz_dy² + dz_dx²))))` | degrees |
| `aspect_deg` | `degrees(arctan2(−dz_dx, dz_dy))` circular mean, 0=N clockwise | degrees |
| `tpi_m` | `center_pixel_elevation − nanmean(window)` | metres |
| `curvature` | `nanmean(Laplacian over 5×5 center kernel)` | m⁻¹ |
| `heat_load_index` | `(1 − cos(aspect_rad − equatorial_dir)) / 2 × sin(slope_rad)` | dimensionless [0--~0.8] |

**Slope computation:** The slope is derived from numpy central differences applied to the elevation window. Gradients in the row direction (north-south) are divided by the arc-second pixel size in metres (≈ 30.87 m), and gradients in the column direction (east-west) are divided by `30.87 × cos(lat)` to account for meridian convergence at higher latitudes. The result is the mean slope angle over the 640m footprint, equivalent to the area-average of the per-pixel first-order terrain gradient.

**Aspect computation:** Aspect is derived from the same numpy central-difference gradients as slope. The circular mean of per-pixel aspect values is taken to correctly handle the 0°/360° wrap-around (e.g. a footprint that is mostly NNW-facing is not averaged to 180°). All arithmetic uses unit vectors on the unit circle before converting back to degrees.

**TPI (Topographic Position Index):** The center pixel of the 64×64 window is compared to the nanmean of the entire window. Positive values indicate the center is elevated relative to its surroundings (ridge, hill crest). Negative values indicate a depression (valley floor, hollow, bowl). A value near zero indicates a planar or mid-slope position.

**Curvature:** The Laplacian (`d²z/dx² + d²z/dy²`) measures the local concavity or convexity of the terrain surface. **Positive values indicate concave terrain** (converging flow, water-collecting -- valley floors, bowls); **negative values indicate convex terrain** (diverging flow, fast drainage -- ridges, domes). The curvature is estimated as the nanmean of the Laplacian over a 5×5-pixel kernel (~50 m × 50 m) centered on the analysis point, rather than the mean over the full 640m window. The center-point kernel is preferred because a narrow valley floor exhibits strong local concavity that is diluted when averaged with the surrounding valley walls and ridges at the full-window scale. Pixel-size scaling (metres per pixel) is applied to both gradient passes so the result has correct units (m⁻¹).

**Heat load index (HLI):** A solar radiation proxy that integrates both aspect and slope. `equatorial_dir` is 180° (south) in the Northern Hemisphere and 0° (north) in the Southern Hemisphere, representing the direction of maximum insolation. A flat site (slope = 0) has HLI = 0 regardless of aspect. A south-facing 45° slope in the NH reaches the theoretical maximum (~0.71). HLI is computed zero extra S3 reads: it reuses the gradient arrays already produced for slope and aspect.

### 12.3 Interpretation

| `elevation_range_m` | Terrain character |
|--------------------|--------------------|
| < 10 m | Flat (coastal plain, delta, valley floor) |
| 10-50 m | Rolling (low hills, gentle slopes) |
| 50-200 m | Hilly (moderate topography) |
| > 200 m | Rugged (steep terrain, mountain) |

Higher `elevation_range_m` correlates with better drainage (lower flood risk) but greater landslide susceptibility. Flat low-elevation sites (<5 m, <10 m range) are more susceptible to tidal inundation and storm surge than their `sar_water_freq_5y` alone may indicate, especially outside the NOAA tidal station network.

### 12.4 Report display

The elevation badge appears in the HTML report header as `▲ {min} / {mean} / {max} m · {slope}° slope · ±{range} m relief`, showing the full elevation spread of the 640m analysis window. In the JSON report all nine terrain values are nested under the top-level `elevation` key (`elevation_min_m`, `elevation_m`, `elevation_max_m`, `elevation_range_m`, `slope_deg`, `aspect_deg`, `tpi_m`, `curvature`, `heat_load_index`). Older cached rows that predate v1.18.0 have `null` for `elevation_min_m` and `elevation_max_m`; rows that predate v1.19.0 have `null` for the four new terrain features. The badge falls back to mean-only display when min/max are null.

A **DEM hillshade image** (256×256 PNG) is rendered at report generation time from the stored 64×64 elevation window, base64-encoded, and embedded inline in the HTML report as a data URI. It uses a NW sun angle, a terrain colour LUT, and bicubic upscaling via scipy. No separate endpoint is exposed; the image is omitted silently if no DEM data is available for the location.

---

## 13. Risk scoring

All scores are integers in [0, 100]. A uniform rounding and clamping function is applied to all final values: `score = clamp(round(raw), 0, 100)`.

**Score direction convention:**
- `drought_score`, `wetness_score`, `fire_exposure_score`, `flood_risk_score`, `heat_stress_score`: higher = more risk
- `heat_mitigation_score`: higher = more canopy = less heat risk
- `composite_score`: higher = more overall climate risk

### 11.1 Drought score

Weighted combination of optical and climate components. Only components with available data are included; weights are renormalized to sum to 1.0 when any component is missing.

| Component | Formula | Nominal weight |
|-----------|---------|----------------|
| NDVI anomaly frequency | `ndvi_anomaly_freq_5y × 100` | 0.20 |
| NDVI trend | `clamp((0.05 − slope) / 0.10 × 100,  0, 100)` | 0.20 |
| NDVI mean | `clamp((0.8 − ndvi_mean) / 0.8 × 100,  0, 100)` | 0.15 |
| NDMI moisture stress | `ndmi_moisture_stress_freq_5y × 100` | 0.20 |
| PDSI drought frequency | `pdsi_drought_freq_5y × 100` | 0.25 |
| NDMI trend slope (v1.27) | `clamp(−ndmi_trend / 0.05 × 100,  0, 100)` | 0.15 |
| PDSI trend slope (v1.27) | `clamp(−pdsi_trend / 0.50 × 100,  0, 100)` | 0.15 |

Trend slope mapping (NDVI): −0.05/yr → 100 (severe decline); +0.05/yr → 0 (recovering). NDVI mean: NDVI = 0 → 100 (bare); NDVI = 0.8 → 0 (dense vegetation). NDMI trend: −0.05/yr → 100 (worsening stress); 0/yr → 0. PDSI trend: −0.50/yr → 100 (worsening drought); 0/yr → 0.

**Terrain drought amplifier (non-urban only):**

```
terrain_amp = 1.0 + min(TERRAIN_DROUGHT_AMP_MAX, (slope_deg − 10.0) / 100.0)
drought_score = min(100, drought_score × terrain_amp)
```

At 25°: +15% amplification; capped at +20%. Only applied when DEM data is available.

**HLI drought amplifier (non-urban only):**

```
hli_amp = 1.0 + min(0.25, heat_load_index × 0.5)
drought_score = min(100, drought_score × hli_amp)
```

**Improving-slope mitigation (non-urban only, applied after terrain amplifiers):**

When the long-term trend is improving (positive slope), the drought score is partially reduced. This is suppressed when any relevant momentum ratio ≥ `MOMENTUM_PRIORITY_THRESHOLD` (1.5): in that case, the recent 12-month trajectory dominates and the long-term slope signal is not allowed to cancel it.

```
max_momentum = max(ndvi_momentum_ratio_1y, ndmi_momentum_ratio_1y,
                   pdsi_momentum_ratio_1y  -- whichever are not None)

if max_momentum < MOMENTUM_PRIORITY_THRESHOLD (1.5):
    if ndmi_trend > 0:
        mitig = min(0.15, ndmi_trend / 0.05 × 0.20)
        drought_score = max(0, drought_score × (1 − mitig))
    if pdsi_trend > 0:
        mitig = min(0.15, pdsi_trend / 0.50 × 0.20)
        drought_score = max(0, drought_score × (1 − mitig))
```

Maximum reduction per slope signal: −15%. Both can apply if present.

**Momentum amplifiers / dampeners (Part B, non-urban only, applied after slope mitigations):**

For each of `ndvi_momentum_ratio_1y`, `ndmi_momentum_ratio_1y`, `pdsi_momentum_ratio_1y`:

```
# Worsening (ratio > 1.0) -- progressive: rate doubles above 2×
excess = ratio − 1.0
raw_amp = excess × MOMENTUM_AMP_SCALE + max(0, excess − 1.0) × MOMENTUM_AMP_SCALE
drought_score = min(100, drought_score × (1 + min(MOMENTUM_AMP_MAX, raw_amp)))

# Improving (0 < ratio < 1.0) -- linear dampening
damp = 1 − min(MOMENTUM_DAMP_MAX, (1 − ratio) × MOMENTUM_AMP_SCALE)
drought_score = max(0, drought_score × damp)
```

`MOMENTUM_AMP_MAX = 0.50`, `MOMENTUM_AMP_SCALE = 0.12`, `MOMENTUM_DAMP_MAX = 0.20`.

Progressive worsening: ratio 2× → +12%, ratio 3× → +36%, ratio ≥ 4.2× → +50% (cap). The doubling above 2× reflects that an acceleration of 3× represents qualitatively more severe deterioration than linear scaling would imply. Improving dampening: ratio 0.5 → −6%, ratio 0.0 → −12% (cap −20%, asymmetric vs. amplification to avoid over-suppression of genuine long-term risk). All three momentum signals apply independently and multiplicatively.

**Active episode boost (Part A, non-urban only, applied last):**

```
if active_drought:
    drought_score = min(100, drought_score × ACTIVE_DROUGHT_BOOST)  # 1.30
```

Forced to 0 for urban locations. Default (all components missing): 50.

### 11.2 Wetness score

```
wetness_score = ndwi_wetness_persistence_5y × 100
```

**NDWI trend adjustment (Part C, bidirectional):**

```
# Rising trend: blend in as 15% weight
if ndwi_trend > 0:
    trend_wet_score = min(100, ndwi_trend / NDWI_TREND_WET_MIN × 100)
    wetness_score   = min(100, wetness_score × 0.85 + trend_wet_score × 0.15)

# Drying trend: dampen wetness score
elif ndwi_trend < 0:
    mitig = min(0.15, −ndwi_trend / NDWI_TREND_WET_MIN × 0.15)
    wetness_score = max(0, wetness_score × (1 − mitig))
```

`NDWI_TREND_WET_MIN = 0.02` index units/year. A rising NDWI trend adds at most +15 pts. A drying trend (site becoming less wet than its 5-year average) reduces wetness score by up to −15%.

Default (no NDWI data): 50.

### 11.3 Fire exposure score

```
fire_exposure_score = min(100,  nbr_burn_freq_5y × 350)
```

`nbr_burn_freq_5y` is an anomaly-based frequency (section 7.4): it counts only months where NBR drops significantly below the site's own seasonal norm, not months where NBR is simply below an absolute threshold. This means the score is near zero for locations with persistently low but normal NBR (dormant prairie, agricultural land, boreal understorey) and elevated only when genuine fire-like departures from the seasonal baseline occur.

Indicative mapping:

| nbr_burn_freq_5y (anomaly) | Score | Interpretation |
|---------------------------|-------|---------------|
| 0.00 -- 0.03 | 0 -- 10 | No meaningful fire signal |
| 0.07 | 25 | Low exposure |
| 0.14 | 50 | Moderate |
| 0.20 -- 0.25 | 70 -- 88 | Significant (one major fire in 5 years) |
| 0.29+ | 100 | High recurrence |

**Fire momentum amplifier (Part B, non-urban only, when NBR data is present):**

```
if nbr_momentum_ratio_1y > 1.0:
    excess  = nbr_momentum_ratio_1y − 1.0
    raw_amp = excess × MOMENTUM_AMP_SCALE + max(0, excess − 1.0) × MOMENTUM_AMP_SCALE
    fire_exposure_score = min(100, fire_exposure_score × (1 + min(MOMENTUM_AMP_MAX, raw_amp)))
```

Same progressive formula as drought momentum: ratio 2× → +12%, ratio 3× → +36%, ratio ≥ 4.2× → +50% cap. This captures sites where recent burn activity has accelerated sharply relative to the 5-year baseline (e.g. post-catastrophic-fire recovery in Mediterranean chaparral). No dampening is applied when `nbr_momentum_ratio_1y < 1.0` (a quieter year does not retroactively reduce the 5-year fire exposure).

**Active episode boost (Part A, non-urban only, applied after momentum, when NBR data is present):**

```
if active_fire:
    fire_exposure_score = min(100, fire_exposure_score × ACTIVE_FIRE_BOOST)  # 1.25
```

Forced to 0 for urban locations (see section 13.1). Default (no NBR data): 0.

### 11.4 Heat mitigation score

```
heat_mitigation_score = clamp(canopy_proxy / 0.8 × 100,  0, 100)
```

A canopy proxy of 0.8 (maximum dense vegetation) maps to 100 (full heat mitigation). This score enters the composite **inverted** as `(100 − heat_mitigation_score)` to represent canopy deficit.

Default (no canopy data): 50.

### 11.5 Flood risk score

Three components are combined, with the NDWI cross-validation veto applied **only to the chronic SAR component**:

```
chronic_score = sar_water_freq_5y × 100
if ndwi_wetness_persistence_5y < SAR_NDWI_CORROBORATION_THRESHOLD (0.05):
    chronic_score × = SAR_NDWI_VETO_FACTOR (0.25)
acute_score = sar_flood_anomaly × 100

# Terrain flash flood potential (static, no observation required)
if elevation_m < TERRAIN_FLASH_ELEV_MAX (300 m) and slope_deg > TERRAIN_FLASH_SLOPE_MIN (3°):
    low_elev_factor = (300 − elevation_m) / 300        # 1.0 at sea level, 0 at 300 m
    slope_factor    = min(1.0, slope_deg / 20.0)       # 1.0 at 20°+
    terrain_flash_score = low_elev_factor × slope_factor × 100
else:
    terrain_flash_score = 0

flood_risk_score = max(chronic_score, acute_score, terrain_flash_score × 0.5)
```

The terrain flash component models fast runoff concentration: it requires **both** low absolute elevation (a flood accumulation zone) **and** significant slope (fast inflow velocity). Flat lowlands and steep highlands both score near zero; low-elevation + steep terrain scores up to 50 (the 0.5 weight ensures observed SAR flooding always dominates when present).

The maximum of all three components ensures that a significant flood event or terrain susceptibility signal is not diluted. Not suppressed for urban locations.

After terrain boosts (TPI and curvature), the active episode boost is applied:

**Active episode boost (Part A):**

```
if active_flood:
    flood_risk_score = min(100, flood_risk_score × ACTIVE_FLOOD_BOOST)  # 1.40
```

This applies regardless of urban classification (flooding is not suppressed for urban locations).

**TPI flood boost:** Valley floors systematically accumulate runoff from surrounding terrain. When `tpi_m < TERRAIN_TPI_FLOOD_THRESHOLD` (−5.0 m), a boost is added after the max-of-components step:

```
tpi_boost = min(TERRAIN_TPI_FLOOD_MAX_BOOST, abs(tpi_m − TERRAIN_TPI_FLOOD_THRESHOLD))
flood_risk_score = min(100, flood_risk_score + tpi_boost)
```

`TERRAIN_TPI_FLOOD_MAX_BOOST = 20.0` pts. At TPI = −25 m: +20 pts (cap reached). Only applied when DEM data is available.

**Curvature flood boost:** Concave terrain concentrates overland flow and promotes ponding. When `curvature > TERRAIN_CURVATURE_THRESHOLD` (+0.0001 m⁻¹, i.e. the terrain is concave at the site center), an additional boost is applied:

```
curvature_boost = min(TERRAIN_CURVATURE_MAX_BOOST,
                      curvature × TERRAIN_CURVATURE_SCALE)
flood_risk_score = min(100, flood_risk_score + curvature_boost)
```

`TERRAIN_CURVATURE_MAX_BOOST = 10.0` pts, `TERRAIN_CURVATURE_SCALE = 50000.0`. Only applied when DEM data is available. Applied after the TPI boost.

**NDWI optical cross-validation veto (chronic component only):**

When Sentinel-2 optical data shows that surface water is essentially absent from the site's history (`ndwi_wetness_persistence_5y < 0.05`) but the SAR chronic frequency is elevated, the two sensors contradict each other. The most common causes are:

- Coastal locations where the SAR window captures open ocean or a harbour: calm sea surface mimics flood backscatter chronically
- Airport runways and large flat rooftops: specularly smooth in C-band, invisible as water in optical NDWI
- Dry lake beds and salt flats with smooth surfaces after drying

The chronic component is discounted by `SAR_NDWI_VETO_FACTOR = 0.25`. It is not zeroed: partial genuine flooding may still be present even when NDWI persistence is below the threshold.

The veto is **not applied** to `sar_flood_anomaly` (the acute component). A normally-dry agricultural site showing a sudden SAR water spike is the strongest possible episodic flood signal -- the optical sensors may have been obscured by cloud, or the flooding may have subsided before the next clear optical pass. Applying the veto to the acute component would suppress genuine flood detections at the locations most at risk from episodic inundation.

Default when no SAR data (`no_sar_data` flag set): 0.

### 11.6 Heat stress score

Weighted combination of TerraClimate components, renormalized when components are missing:

| Component | Formula | Nominal weight |
|-----------|---------|----------------|
| tmax anomaly frequency | `tmax_anomaly_freq_5y × 100` | 0.40 |
| tmax warming trend | `clamp(tmax_trend / 0.05 × 100,  0, 100)` | 0.30 |
| VPD high frequency | `vpd_high_freq_5y × 100` | 0.30 |
| VPD trend slope (v1.27) | `clamp(vpd_trend / VPD_TREND_HIGH_MIN × 100,  0, 100)` | 0.20 |

`VPD_TREND_HIGH_MIN = 0.05 kPa/yr`. tmax trend: 0.05 °C/yr → 100; ≤ 0 → 0. VPD trend: 0.05 kPa/yr → 100; ≤ 0 → 0. Components are weighted and renormalized; absent keys do not change the score.

**Improving VPD trend mitigation:** If `vpd_trend_slope_5y < 0` (atmospheric moisture demand declining), the heat stress score is partially reduced:

```
mitig = min(0.15, −vpd_trend / VPD_TREND_HIGH_MIN × 0.15)
heat_stress_score = max(0, heat_stress_score × (1 − mitig))
```

This is in addition to the dilution already present in the weighted average when the VPD slope component is 0. Maximum reduction: −15%.

**Momentum amplifier / dampener (Part B):** After base computation and VPD mitigation:

```
# Worsening (progressive)
excess  = tmax_momentum_ratio_1y − 1.0
raw_amp = excess × MOMENTUM_AMP_SCALE + max(0, excess − 1.0) × MOMENTUM_AMP_SCALE
heat_stress_score = min(100, heat_stress_score × (1 + min(MOMENTUM_AMP_MAX, raw_amp)))

# Improving
damp = 1 − min(MOMENTUM_DAMP_MAX, (1 − tmax_momentum_ratio_1y) × MOMENTUM_AMP_SCALE)
heat_stress_score = max(0, heat_stress_score × damp)
```

**HLI heat stress amplifier (non-urban only):**

```
hli_amp = 1.0 + min(0.25, heat_load_index × 0.5)
heat_stress_score = min(100, heat_stress_score × hli_amp)
```

Only applied when DEM data is available.

Default (no TerraClimate data, `no_terraclimate_data` flag): 50.

### 11.7 Landslide risk score

A standalone terrain hazard score (0-100) derived from the terrain DTM (3DEP for US locations, GLO-30 globally). It is **not included in the composite** -- landslide is an independent geophysical hazard orthogonal to the climate risk dimensions. It is surfaced separately in the API response and the HTML report.

**Physical basis:** Slope angle is the primary driver of gravitational shear stress. Terrain relief (elevation range of the 640m footprint) is a secondary proxy for slope length and material accumulation potential.

```
slope_score  = min(100, slope_deg / TERRAIN_LANDSLIDE_SLOPE_MAX × 100)
relief_score = min(100, elevation_range_m / TERRAIN_LANDSLIDE_RELIEF_MAX × 100)
landslide_risk_score = 0.70 × slope_score + 0.30 × relief_score
```

Indicative mapping:

| slope_deg | landslide_risk_score (flat terrain) | Interpretation |
|-----------|-------------------------------------|----------------|
| < 5° | < 20 | Negligible slope hazard |
| 10° | 28 | Low |
| 15° | 42 | Moderate |
| 20° | 56 | Elevated |
| 25°+ | 70-100 | High to very high |

Default when no DEM data (`no_dem_data` flag): 0.

The gauge is hidden in the HTML report when `slope_deg` is null (no DEM data) and the score is 0.

### 11.8 Composite score

**Urban locations** (climate-zone weights are not applicable to impervious surfaces):

```
composite = 0.60 × (100 − heat_mitigation_score)
          + 0.15 × wetness_score
          + 0.15 × flood_risk_score
          + 0.10 × heat_stress_score
```

The canopy deficit term (60%) dominates because the primary long-term climate risk for urban environments is the urban heat island effect, which is modulated by vegetation and shading.

**Non-urban locations** (climate-zone-weighted):

```
composite = w_drought     × drought_score
          + w_wetness     × wetness_score
          + w_fire        × fire_exposure_score
          + w_heat_inv    × (100 − heat_mitigation_score)
          + w_flood       × flood_risk_score
          + w_heat_stress × heat_stress_score
```

Climate zone weights (Köppen classification; all rows sum to 1.0):

| Zone | Code prefix | drought | wetness | fire | heat_inv | flood | heat_stress |
|------|------------|---------|---------|------|----------|-------|-------------|
| Tropical | A | 0.07 | 0.30 | 0.08 | 0.20 | 0.18 | 0.17 |
| Arid | B | 0.38 | 0.04 | 0.16 | 0.20 | 0.04 | 0.18 |
| Mediterranean | Cs | 0.20 | 0.06 | 0.28 | 0.14 | 0.12 | 0.20 |
| Temperate humid | C (non-Cs) | 0.16 | 0.16 | 0.12 | 0.20 | 0.16 | 0.20 |
| Continental / Boreal | D | 0.12 | 0.12 | 0.24 | 0.20 | 0.12 | 0.20 |
| Polar / Alpine | E | 0.06 | 0.14 | 0.04 | 0.44 | 0.12 | 0.20 |
| Unknown / default | -- | 0.22 | 0.16 | 0.14 | 0.16 | 0.12 | 0.20 |

Köppen classification is derived from the location centroid using a 1/12° gridded climatology. The "Cs" (Mediterranean) key takes precedence over the general "C" key; all other zones match on the first letter.

---

## 14. Quality metadata

Each computation returns a quality object:

| Field | Description |
|-------|-------------|
| `months_total` | Total calendar months in the analysis window |
| `months_observed` | Months for which at least one valid scene was obtained |
| `mean_cloud_fraction` | Mean per-scene cloud fraction across all accepted scenes |
| `quality_score` | Composite quality score in [0, 1] (section 7.8) |
| `flags` | List of string flags; see below |

Quality flags:

| Flag | Trigger condition |
|------|------------------|
| `urban_location` | `is_urban == True` |
| `tidal_zone` | `is_tidal_zone == True` (nearest NOAA tidal station within `TIDAL_ZONE_RADIUS_KM`) |
| `no_sar_data` | No Sentinel-1 scenes found or all scenes failed to read |
| `sar_burn_suppression` | At least one SAR month excluded due to co-located NBR burn signal |
| `no_terraclimate_data` | TerraClimate fetch failed for all requested variables |
| `no_dem_data` | DEM tile read failed for all sources (3DEP + GLO-30), or < 25% valid pixels (ocean tile edge, missing coverage) |

---

## 15. Known limitations and spectral confounds

### 13.1 NBR false positives on urban impervious surfaces

Concrete, asphalt, and other impervious surfaces have low NIR reflectance and moderate-to-high SWIR2 reflectance, producing NBR values typically in [−0.1, 0.2] -- the same range as burned vegetation. Dense urban areas (e.g. Boston downtown) routinely produce `nbr_burn_freq_5y` of 60 -- 90% in the absence of any fire. The `fire_exposure_score` is therefore suppressed to 0 for all locations classified as urban (section 10).

### 13.2 SAR false positives from post-fire bare soil

Post-fire burn scars leave bare soil and ash with VV backscatter values that can fall below the 75 DN water threshold. This produces false "water" detections in SAR scenes acquired over recently burned areas. The burn suppression (section 8.3) mitigates this by excluding SAR scenes from months where co-located NBR confirms a burn signal. Residual risk: if the optical SCL mask discards the S2 scene for the same month (e.g. smoke), NBR is not available and burn suppression does not apply.

### 13.3 SAR snow / water confusion and steep-terrain artefacts

Smooth compacted snow is specularly reflective in C-band, producing backscatter in the water DN range. The snow suppression filter (section 8.2) addresses this for the chronic frequency metric. Flooded agricultural fields can also exhibit elevated NDSI due to specular reflection from waterlogged soil surfaces; the flood anomaly metric deliberately omits snow suppression for this reason.

Rocky or snow-covered slopes at certain look angles produce geometrically induced low-backscatter returns even when no water is present. This artefact is look-angle-dependent and therefore orbit-specific: one orbit may record a slope as "water" while a second orbit from a different direction records it as land. The DEM slope mask (section 8.1) addresses this by excluding pixels steeper than 15° from the water fraction computation, so a hillside pixel never contributes to a false-flood count. Residual risk: slopes that are exactly at the threshold angle, or locations where the 30 m DEM tile is unavailable, may still produce slightly elevated fractions.

### 13.4 NDWI and SAR do not measure the same quantity

NDWI (McFeeters) detects standing surface water in optical data. SAR VV flood detection responds to specular reflection from flat water surfaces. The two are complementary but not equivalent: NDWI is occluded by cloud cover; SAR is insensitive to shallow subsurface saturation. `wetness_score` (from NDWI) and `flood_risk_score` (from SAR) capture different aspects of water exposure.

### 13.5 TerraClimate spatial resolution

TerraClimate operates at 1/24° (~4 km). This resolution captures mesoscale climate patterns but not local topographic effects. Urban heat islands, valley cold traps, and coastal fog regimes are not resolved. Features derived from TerraClimate should be interpreted as regional background climate rather than local microclimate.

### 13.6 SAR specular false positives at coastal and smooth-surface locations

Certain non-water surfaces produce VV backscatter that falls below the 75 DN water threshold and is indistinguishable from calm open water by SAR alone:

- **Coastal ocean / harbours:** calm sea surface at low wind speeds is specularly reflective in C-band. A 640 m window at a coastal location may partially overlap the water body, producing elevated SAR water fractions even when the land parcel itself is never flooded.
- **Airport runways and large flat rooftops:** smooth impervious surfaces also produce specular C-band returns.
- **Dry lake beds and salt flats:** smooth surface after drying can persist.

The NDWI optical cross-validation veto (section 11.5) addresses this by discounting the SAR flood score when optical data shows no surface water history at the location. Residual limitation: a coastal site that has genuine flooding (overtopped sea walls, storm surge) may also have persistent optical water nearby and would not be vetoed -- the veto is conservative and does not suppress sites with legitimate NDWI water presence.

### 13.7 640 m window and land cover heterogeneity

The fixed 640 m × 640 m footprint means that a point location in a mixed environment (e.g. a building at the edge of a park) integrates signal from surrounding land cover. The reported NDVI, BSI, and canopy proxy reflect the 640 m neighbourhood average, not the specific parcel land cover. This is by design: the intent is to capture the broader landscape context relevant to climate risk, not parcel-specific green space.

---

## 16. Parameter reference

All thresholds are configurable via environment variables. Defaults are listed below.

### Spectral thresholds

| Parameter | Default | Applied in |
|-----------|---------|-----------|
| `NDVI_ANOMALY_THRESHOLD` | 0.1 NDVI units | `ndvi_anomaly_freq_5y` |
| `NDWI_WET_THRESHOLD` | 0.0 | `ndwi_wetness_persistence_5y` |
| `NDMI_STRESS_THRESHOLD` | 0.0 | `ndmi_moisture_stress_freq_5y` |
| `NBR_BURN_THRESHOLD` | 0.1 | Chart bar colour only (cosmetic); all fire detection uses anomaly threshold |
| `NBR_ANOMALY_THRESHOLD` | 0.15 | NBR drop below site seasonal climatology required to flag a fire anomaly |
| `NBR_MIN_CONSECUTIVE` | 3 | Minimum calendar-consecutive anomaly months for fire detection and SAR burn suppression |
| `NDSI_SNOW_THRESHOLD` | 0.4 | `ndsi_snow_persistence_5y`, SAR snow suppression |
| `BSI_BARE_THRESHOLD` | 0.0 | `bsi_bare_soil_freq_5y` |

### SAR parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `SAR_WATER_DN_THRESHOLD` | 75 | VV DN below which a pixel is classified as water |
| `SAR_MIN_WATER_PIXEL_FRACTION` | 0.35 | Absolute flood threshold: minimum water pixel fraction per scene |
| `SAR_FLOOD_MAD_K` | 2.0 | MAD multiplier for orbit-stratified adaptive threshold |
| `SAR_MIN_ANOMALY_FRACTION` | 0.05 | Floor on adaptive threshold (prevents noise at low-baseline orbits) |
| `SAR_MIN_CONSECUTIVE_FLOOD_MONTHS` | 2 | Minimum calendar-consecutive anomalous months to count for the chronic MAD-based frequency |
| `SAR_NDWI_CORROBORATION_THRESHOLD` | 0.05 | Optical water persistence below which the SAR chronic score is vetoed |
| `SAR_NDWI_VETO_FACTOR` | 0.25 | Multiplier applied to the chronic flood score when NDWI corroboration is absent |
| `SAR_ACTIVE_FLOOD_MIN_NDWI` | 0.08 | `active_flood` corroboration: minimum NDWI persistence (optical water history required) |
| `SAR_ACTIVE_FLOOD_STRONG_ANOMALY` | 0.35 | `active_flood` strong-anomaly override: flag regardless of corroboration |
| `DEM_FLAT_SLOPE_THRESHOLD` | 15.0° | Per-pixel slope above which the pixel is excluded from SAR water fraction (numerator and denominator) |

### Elevation parameters (hybrid DTM)

| Parameter | Default | Description |
|-----------|---------|-------------|
| `DEM_3DEP_BUCKET` | `prd-tnm` | S3 bucket for USGS 3DEP 1" tiles (US primary, us-west-2) |
| `DEM_3DEP_REGION` | `us-west-2` | Bucket region for 3DEP GDAL virtual filesystem routing |
| `DEM_AWS_BUCKET` | `copernicus-dem-30m` | S3 bucket for GLO-30 COG tiles (global fallback) |
| `DEM_AWS_REGION` | `eu-central-1` | Bucket region for GLO-30 GDAL virtual filesystem routing |

### Terrain risk scoring thresholds

| Parameter | Default | Applied in |
|-----------|---------|-----------|
| `TERRAIN_LANDSLIDE_SLOPE_MAX` | 25.0° | `landslide_risk_score` slope component (maps to 100) |
| `TERRAIN_LANDSLIDE_RELIEF_MAX` | 300.0 m | `landslide_risk_score` relief component (maps to 100) |
| `TERRAIN_FLASH_ELEV_MAX` | 300.0 m | Terrain flash flood: elevation above which contribution = 0 |
| `TERRAIN_FLASH_SLOPE_MIN` | 3.0° | Terrain flash flood: minimum slope to activate |
| `TERRAIN_FLASH_SLOPE_MAX` | 20.0° | Terrain flash flood: slope mapped to 1.0 |
| `TERRAIN_DROUGHT_SLOPE_MIN` | 10.0° | Terrain drought amplifier: slope threshold for activation |
| `TERRAIN_DROUGHT_AMP_MAX` | 0.20 | Terrain drought amplifier: maximum multiplier (+20%) |
| `TERRAIN_HLI_THRESHOLD` | 0.05 | HLI above which the HLI amplifier activates for drought and heat stress |
| `TERRAIN_HLI_AMP_MAX` | 0.25 | Maximum HLI multiplier (+25%) for drought and heat stress scores |
| `TERRAIN_HLI_FACTOR` | 0.5 | Scaling factor: `hli_amp = 1.0 + min(HLI_AMP_MAX, HLI × HLI_FACTOR)` |
| `TERRAIN_TPI_FLOOD_THRESHOLD` | −5.0 m | TPI below which the valley floor flood boost activates |
| `TERRAIN_TPI_FLOOD_MAX_BOOST` | 20.0 pts | Maximum flood score boost from TPI (valley floor) |
| `TERRAIN_CURVATURE_THRESHOLD` | −0.0001 m⁻¹ | Curvature below which the concave terrain flood boost activates |
| `TERRAIN_CURVATURE_MAX_BOOST` | 10.0 pts | Maximum flood score boost from curvature (concave terrain) |
| `TERRAIN_CURVATURE_SCALE` | 50000.0 | Linear scaling factor mapping curvature magnitude to boost points |

### NOAA tidal zone parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `TIDAL_ZONE_RADIUS_KM` | 30.0 km | Maximum distance to nearest NOAA tidal station for tidal zone classification |
| `TIDAL_ZONE_MAX_ELEV_M` | 10.0 m | Maximum elevation (MSL) for tidal zone classification; sites above this are never classified as tidal |
| `NOAA_STATION_REFRESH_DAYS` | 30 days | Age after which the cached station list is refreshed on next server startup |

### Urban detection thresholds

| Parameter | Default | Path |
|-----------|---------|------|
| `URBAN_MIN_NDVI_THRESHOLD` | 0.12 | Guard: below this NDVI the site is naturally barren; both paths suppressed |
| `URBAN_BSI_FREQ_STRONG_THRESHOLD` | 0.65 | Path 1 (strong signal alone) |
| `URBAN_BSI_FREQ_THRESHOLD` | 0.50 | Path 2 (combined) |
| `URBAN_NDVI_THRESHOLD` | 0.25 | Path 2 |
| `URBAN_CANOPY_THRESHOLD` | 0.25 | Path 2 |

### Trend-aware scoring parameters (v1.27.0)

**Active episode multipliers (Part A):**

| Parameter | Default | Applied to |
|-----------|---------|-----------|
| `ACTIVE_FLOOD_BOOST` | 1.40 | `flood_risk_score` when `active_flood = 1` |
| `ACTIVE_DROUGHT_BOOST` | 1.30 | `drought_score` when `active_drought = 1` (non-urban) |
| `ACTIVE_FIRE_BOOST` | 1.25 | `fire_exposure_score` when `active_fire = 1` (non-urban, NBR present) |

**Momentum amplifier / dampener parameters (Part B):**

| Parameter | Default | Description |
|-----------|---------|-------------|
| `MOMENTUM_AMP_MAX` | 0.50 | Cap on fractional amplification per momentum signal (+50% max) |
| `MOMENTUM_AMP_SCALE` | 0.12 | Base rate per unit of excess ratio; doubles above 2×. Ratio 2× → +12%, ratio 3× → +36%, ratio 4.2× → +50% cap |
| `MOMENTUM_DAMP_MAX` | 0.20 | Cap on fractional dampening for improving trajectory (−20% max) |
| `MOMENTUM_PRIORITY_THRESHOLD` | 1.5 | When any relevant worsening momentum ≥ this value, improving long-term slope mitigations are suppressed for that sub-score |

**Slope sub-component thresholds (Part C):**

| Parameter | Default | Applied in |
|-----------|---------|-----------|
| `NDWI_TREND_WET_MIN` | 0.02 index/yr | NDWI positive trend maps to 100 pts at this slope |
| `NDMI_TREND_STRESS_MAX` | −0.05 index/yr | Most negative NDMI slope maps to 100 pts drought |
| `VPD_TREND_HIGH_MIN` | 0.05 kPa/yr | VPD slope maps to 100 pts heat stress at this value |
| `PDSI_TREND_DROUGHT_MAX` | −0.5 units/yr | Most negative PDSI slope maps to 100 pts drought |

### TerraClimate thresholds

| Parameter | Default | Applied in |
|-----------|---------|-----------|
| `TERRACLIMATE_VPD_HIGH_THRESHOLD` | 1.5 kPa | `vpd_high_freq_5y` |
| `TERRACLIMATE_PDSI_DROUGHT_THRESHOLD` | −2.0 | `pdsi_drought_freq_5y`, `pdsi_momentum_ratio_1y` |
| `TERRACLIMATE_TMAX_ANOMALY_SIGMA` | 1.0 σ | `tmax_anomaly_freq_5y`, `tmax_momentum_ratio_1y` |

### Growing season

| Parameter | Default | Applied to |
|-----------|---------|-----------|
| `GROWING_SEASON_LAT_THRESHOLD` | 33.0° | Latitude boundary within C/D zones (abs lat) |
| `TEMPERATE_SEASON_MONTHS` | [5,6,7,8,9] | C/D zones, abs lat ≥ 33°, NH |
| `SUBTROPICAL_SEASON_MONTHS` | [3,4,5,6,7,8,9,10,11] | C/D zones, abs lat < 33°, NH |

SH values are derived automatically by shifting NH months by +6. Tropical, Arid, Mediterranean, and Polar zones have fixed month sets independent of latitude threshold.

### Scene selection

| Parameter | Default | Description |
|-----------|---------|-------------|
| `MAX_SCENES_PER_MONTH` | 2 | S2 scenes per calendar month |
| `MAX_TOTAL_SCENES` | 120 | Hard cap on total S2 scenes processed |
| `STAC_MAX_ITEMS` | 2000 | STAC fetch budget (decoupled from processing cap to prevent oldest months being dropped in dense-overpass areas) |
| `SAR_MAX_SCENES_PER_MONTH` | 2 | S1 scenes per calendar month |
| `SAR_MAX_TOTAL_SCENES` | 120 | Hard cap on total S1 scenes |
| `MIN_VALID_PIXEL_FRACTION` | 0.05 | Minimum fraction to accept a scene (5% of 4,096 pixels = 205 px) |
| `COG_WINDOW_SIZE` | 64 | Window size in native pixels |

---

*Processing version `s2l2a-v1.27.0` / score version `risk-v1.17.0`. Trend-aware scoring (active boosts, momentum amplifiers, slope sub-components) introduced in v1.27.0/v1.15.0. Bidirectional mitigations (improving trends reduce scores) added in v1.16.0. Progressive momentum formula, fire momentum (`nbr_momentum_ratio_1y`), and momentum priority threshold added in v1.17.0.*
