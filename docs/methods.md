# Location Sentinel -- Scientific Methods Reference

**Version:** processing `s2l2a-v1.14.0` / scoring `risk-v1.12.0`
**Date:** 2026-02-28
**Scope:** Data sources, pixel-level processing, spectral indices, feature derivation, urban detection, risk scoring. Infrastructure, routing, and persistence are excluded.

---

## Table of contents

1. [Data sources](#1-data-sources)
2. [Spatial footprint](#2-spatial-footprint)
3. [Scene selection](#3-scene-selection)
4. [Cloud and quality masking (SCL)](#4-cloud-and-quality-masking-scl)
5. [Sentinel-2 spectral indices](#5-sentinel-2-spectral-indices)
6. [Monthly aggregation](#6-monthly-aggregation)
7. [Long-term optical features](#7-long-term-optical-features)
8. [Sentinel-1 SAR flood analysis](#8-sentinel-1-sar-flood-analysis)
9. [TerraClimate gridded climate features](#9-terraclimate-gridded-climate-features)
10. [Urban detection](#10-urban-detection)
11. [Risk scoring](#11-risk-scoring)
12. [Quality metadata](#12-quality-metadata)
13. [Known limitations and spectral confounds](#13-known-limitations-and-spectral-confounds)
14. [Parameter reference](#14-parameter-reference)

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

### 7.3 NDMI features

**`ndmi_mean_5y`** -- Mean of all valid monthly NDMI values.

**`ndmi_moisture_stress_freq_5y`** -- Fraction of months where NDMI < 0:

```
ndmi_moisture_stress_freq_5y = count(NDMI_monthly < 0) / count(observed months)
```

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

### 7.8 Quality score

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
water_pixels = pixels where 0 < DN < SAR_WATER_DN_THRESHOLD (75 DN)
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

### 9.4 PDSI features

**`pdsi_mean_5y`** -- Mean PDSI over the analysis window. PDSI > 0 = wetter than normal; PDSI < 0 = drier; PDSI < −2 = moderate drought; PDSI < −4 = extreme drought (Palmer 1965 classification).

**`pdsi_drought_freq_5y`** -- Fraction of months where PDSI < −2.0 (`TERRACLIMATE_PDSI_DROUGHT_THRESHOLD`):

```
pdsi_drought_freq_5y = count(PDSI_monthly < -2.0) / count(valid months)
```

---

## 10. Urban detection

Urban classification is determined by a two-path OR logic gate applied to the optical features:

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

## 11. Risk scoring

All scores are integers in [0, 100]. A uniform rounding and clamping function is applied to all final values: `score = clamp(round(raw), 0, 100)`.

**Score direction convention:**
- `drought_score`, `wetness_score`, `fire_exposure_score`, `flood_risk_score`, `heat_stress_score`: higher = more risk
- `heat_mitigation_score`: higher = more canopy = less heat risk
- `composite_score`: higher = more overall climate risk

### 11.1 Drought score

Weighted combination of four optical components and one climate component. Only components with available data are included; weights are renormalized to sum to 1.0 when any component is missing.

| Component | Formula | Nominal weight |
|-----------|---------|----------------|
| NDVI anomaly frequency | `ndvi_anomaly_freq_5y × 100` | 0.20 |
| NDVI trend | `clamp((0.05 − slope) / 0.10 × 100,  0, 100)` | 0.20 |
| NDVI mean | `clamp((0.8 − ndvi_mean) / 0.8 × 100,  0, 100)` | 0.15 |
| NDMI moisture stress | `ndmi_moisture_stress_freq_5y × 100` | 0.20 |
| PDSI drought frequency | `pdsi_drought_freq_5y × 100` | 0.25 |

Trend slope mapping: a slope of −0.05 NDVI/yr maps to 100 (severe decline); +0.05 NDVI/yr maps to 0 (vegetation recovering). NDVI mean mapping: NDVI = 0 maps to 100 (bare); NDVI = 0.8 maps to 0 (dense healthy vegetation).

Forced to 0 for urban locations.

Default (all components missing): 50.

### 11.2 Wetness score

```
wetness_score = ndwi_wetness_persistence_5y × 100
```

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

Forced to 0 for urban locations (see section 13.1).

Default (no NBR data): 0.

### 11.4 Heat mitigation score

```
heat_mitigation_score = clamp(canopy_proxy / 0.8 × 100,  0, 100)
```

A canopy proxy of 0.8 (maximum dense vegetation) maps to 100 (full heat mitigation). This score enters the composite **inverted** as `(100 − heat_mitigation_score)` to represent canopy deficit.

Default (no canopy data): 50.

### 11.5 Flood risk score

The chronic and acute SAR components are combined with the NDWI cross-validation veto applied **only to the chronic component**:

```
chronic_score = sar_water_freq_5y × 100
if ndwi_wetness_persistence_5y < SAR_NDWI_CORROBORATION_THRESHOLD (0.05):
    chronic_score × = SAR_NDWI_VETO_FACTOR (0.25)
acute_score = sar_flood_anomaly × 100
flood_risk_score = max(chronic_score, acute_score)
```

The maximum of the two components ensures that a single significant flood event (captured by the anomaly metric) is not diluted by years of dry baseline in the chronic frequency. Not suppressed for urban locations; flood risk applies regardless of land cover.

**NDWI optical cross-validation veto (chronic component only):**

When Sentinel-2 optical data shows that surface water is essentially absent from the site's history (`ndwi_wetness_persistence_5y < 0.05`) but the SAR chronic frequency is elevated, the two sensors contradict each other. The most common causes are:

- Coastal locations where the SAR window captures open ocean or a harbour: calm sea surface mimics flood backscatter chronically
- Airport runways and large flat rooftops: specularly smooth in C-band, invisible as water in optical NDWI
- Dry lake beds and salt flats with smooth surfaces after drying

The chronic component is discounted by `SAR_NDWI_VETO_FACTOR = 0.25`. It is not zeroed: partial genuine flooding may still be present even when NDWI persistence is below the threshold.

The veto is **not applied** to `sar_flood_anomaly` (the acute component). A normally-dry agricultural site showing a sudden SAR water spike is the strongest possible episodic flood signal -- the optical sensors may have been obscured by cloud, or the flooding may have subsided before the next clear optical pass. Applying the veto to the acute component would suppress genuine flood detections at the locations most at risk from episodic inundation.

Default when no SAR data (`no_sar_data` flag set): 0.

### 11.6 Heat stress score

Weighted combination of three TerraClimate components, renormalized when components are missing:

| Component | Formula | Nominal weight |
|-----------|---------|----------------|
| tmax anomaly frequency | `tmax_anomaly_freq_5y × 100` | 0.40 |
| tmax warming trend | `clamp(tmax_trend / 0.05 × 100,  0, 100)` | 0.30 |
| VPD high frequency | `vpd_high_freq_5y × 100` | 0.30 |

Trend mapping: 0.05 °C/yr maps to 100; 0 °C/yr maps to 0; negative trends are clamped to 0.

Default (no TerraClimate data, `no_terraclimate_data` flag): 50.

### 11.7 Composite score

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

## 12. Quality metadata

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
| `no_sar_data` | No Sentinel-1 scenes found or all scenes failed to read |
| `sar_burn_suppression` | At least one SAR month excluded due to co-located NBR burn signal |
| `no_terraclimate_data` | TerraClimate fetch failed for all requested variables |

---

## 13. Known limitations and spectral confounds

### 13.1 NBR false positives on urban impervious surfaces

Concrete, asphalt, and other impervious surfaces have low NIR reflectance and moderate-to-high SWIR2 reflectance, producing NBR values typically in [−0.1, 0.2] -- the same range as burned vegetation. Dense urban areas (e.g. Boston downtown) routinely produce `nbr_burn_freq_5y` of 60 -- 90% in the absence of any fire. The `fire_exposure_score` is therefore suppressed to 0 for all locations classified as urban (section 10).

### 13.2 SAR false positives from post-fire bare soil

Post-fire burn scars leave bare soil and ash with VV backscatter values that can fall below the 75 DN water threshold. This produces false "water" detections in SAR scenes acquired over recently burned areas. The burn suppression (section 8.3) mitigates this by excluding SAR scenes from months where co-located NBR confirms a burn signal. Residual risk: if the optical SCL mask discards the S2 scene for the same month (e.g. smoke), NBR is not available and burn suppression does not apply.

### 13.3 SAR snow / water confusion

Smooth compacted snow is specularly reflective in C-band, producing backscatter in the water DN range. The snow suppression filter (section 8.2) addresses this for the chronic frequency metric. Flooded agricultural fields can also exhibit elevated NDSI due to specular reflection from waterlogged soil surfaces; the flood anomaly metric deliberately omits snow suppression for this reason.

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

## 14. Parameter reference

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
| `SAR_NDWI_VETO_FACTOR` | 0.25 | Multiplier applied to the chronic flood score when NDWI corroboration is absent (does not affect acute anomaly) |

### Urban detection thresholds

| Parameter | Default | Path |
|-----------|---------|------|
| `URBAN_BSI_FREQ_STRONG_THRESHOLD` | 0.65 | Path 1 (strong signal alone) |
| `URBAN_BSI_FREQ_THRESHOLD` | 0.50 | Path 2 (combined) |
| `URBAN_NDVI_THRESHOLD` | 0.25 | Path 2 |
| `URBAN_CANOPY_THRESHOLD` | 0.25 | Path 2 |

### TerraClimate thresholds

| Parameter | Default | Applied in |
|-----------|---------|-----------|
| `TERRACLIMATE_VPD_HIGH_THRESHOLD` | 1.5 kPa | `vpd_high_freq_5y` |
| `TERRACLIMATE_PDSI_DROUGHT_THRESHOLD` | −2.0 | `pdsi_drought_freq_5y` |
| `TERRACLIMATE_TMAX_ANOMALY_SIGMA` | 1.0 σ | `tmax_anomaly_freq_5y` |

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
| `MAX_TOTAL_SCENES` | 120 | Hard cap on total S2 scenes |
| `SAR_MAX_SCENES_PER_MONTH` | 2 | S1 scenes per calendar month |
| `SAR_MAX_TOTAL_SCENES` | 120 | Hard cap on total S1 scenes |
| `MIN_VALID_PIXEL_FRACTION` | 0.05 | Minimum fraction to accept a scene (5% of 4,096 pixels = 205 px) |
| `COG_WINDOW_SIZE` | 64 | Window size in native pixels |

---

*Document generated from source code at commit `d4300b7` (master), processing version `s2l2a-v1.14.0`, score version `risk-v1.12.0`.*
