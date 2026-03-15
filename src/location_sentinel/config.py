from pydantic import field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    model_config = {"env_prefix": "", "case_sensitive": True, "env_file": ".env", "env_file_encoding": "utf-8"}

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def parse_cors_origins(cls, v: object) -> list[str]:
        if isinstance(v, list):
            return v
        if isinstance(v, str):
            # Accept JSON array or comma-separated string
            v = v.strip()
            if v.startswith("["):
                import json
                return json.loads(v)
            return [o.strip() for o in v.split(",") if o.strip()]
        return v

    # Environment
    ENV: str = "development"  # "development" | "production"

    # Logging
    LOG_LEVEL: str = "INFO"

    # STAC
    STAC_ENDPOINTS: str = "https://earth-search.aws.element84.com/v1"
    STAC_COLLECTION: str = "sentinel-2-l2a"

    # AWS COG source for Sentinel-2 (public bucket, no auth)
    AWS_SENTINEL_BUCKET: str = "sentinel-cogs"
    AWS_SENTINEL_REGION: str = "us-west-2"

    # Copernicus GLO-30 DEM (public S3, no-sign) -- global fallback
    DEM_AWS_BUCKET: str = "copernicus-dem-30m"
    DEM_AWS_REGION: str = "eu-central-1"

    # USGS 3DEP 1" (true lidar DTM, public S3, no-sign) -- US primary
    DEM_3DEP_BUCKET: str = "prd-tnm"
    DEM_3DEP_REGION: str = "us-west-2"

    # Beck et al. (2023) 1km Köppen-Geiger COG (private bucket, uses AWS credential chain)
    KOEPPEN_COG_URL: str = "https://klimex-590184008642-us-west-2-an.s3.us-west-2.amazonaws.com/climates.tif"
    KOEPPEN_AWS_REGION: str = "us-west-2"

    # Overture Maps buildings (public S3, us-west-2)
    # Update OVERTURE_RELEASE to the latest available release:
    #   aws s3 ls s3://overturemaps-us-west-2/release/ --no-sign-request
    OVERTURE_BUCKET: str = "overturemaps-us-west-2"
    OVERTURE_RELEASE: str = "2026-02-18.0"

    # SAR / Sentinel-1 GRD
    SAR_STAC_COLLECTION: str = "sentinel-1-grd"
    SAR_AWS_BUCKET: str = "sentinel-s1-l1c"
    SAR_AWS_REGION: str = "eu-central-1"
    # Water detection threshold in uint16 DN.
    # Calibration: sigma0_dB = 20 * log10(DN) - 83.
    # Empirical DN ranges for sentinel-s1-l1c IW GRD:
    #   Thermal noise floor:  ~35 DN  (~-52 dB)
    #   Calm water (specular): 35–70 DN  (~-52 to -45 dB)
    #   Vegetated land:       100–250 DN (~-43 to -37 dB)
    #   Land mean observed:   ~141 DN  (~-40 dB)
    #   Urban/corner reflect: 500+ DN  (~-30 dB and above)
    # Threshold at 75 DN sits above noise floor but below land mean.
    SAR_WATER_DN_THRESHOLD: int = 75
    # Minimum fraction of window pixels below threshold for a scene to count as flooded.
    # Raised from 0.05 to 0.35 to avoid false positives from mixed land/shadow pixels.
    SAR_MIN_WATER_PIXEL_FRACTION: float = 0.35
    # MAD multiplier for the orbit-stratified anomaly threshold.
    # Per-orbit anomaly threshold = max(median + SAR_FLOOD_MAD_K × MAD, SAR_MIN_ANOMALY_FRACTION).
    # k=2 is robust to flood outliers (MAD is not inflated by the anomalies themselves,
    # unlike std). The floor (SAR_MIN_ANOMALY_FRACTION) prevents instrument noise and
    # coastal backscatter roughness from triggering false positives at low-baseline orbits.
    # The absolute threshold (SAR_MIN_WATER_PIXEL_FRACTION) still applies independently
    # for chronically wet locations; freq = max(absolute_freq, anomaly_freq).
    SAR_FLOOD_MAD_K: float = 2.0
    # Minimum water fraction a scene must reach to be counted as anomalously flooded.
    # Even if median + k*MAD is lower, scenes below this floor are not flagged.
    # 5% means at least ~200 of the 4096 pixels in the window look like water.
    SAR_MIN_ANOMALY_FRACTION: float = 0.05
    # Minimum number of calendar-consecutive anomalous months required to count
    # as a genuine chronic flood event. Suppresses single-pass instrument noise
    # (wind roughening, specular glint from individual scenes).
    SAR_MIN_CONSECUTIVE_FLOOD_MONTHS: int = 2
    SAR_MAX_SCENES_PER_MONTH: int = 2
    SAR_MAX_TOTAL_SCENES: int = 120
    # NDWI optical cross-validation veto for SAR flood score.
    # If ndwi_wetness_persistence_5y < threshold (S2 optical shows no surface water)
    # but SAR water fraction is elevated, the two sensors contradict each other.
    # Likely cause: specular C-band backscatter from ocean, runways, or flat roofs.
    SAR_NDWI_CORROBORATION_THRESHOLD: float = 0.05  # < 5% optical water months → no corroboration
    SAR_NDWI_VETO_FACTOR: float = 0.25              # multiply flood score by this when unconfirmed
    # When chronic SAR water fraction exceeds this threshold but NDWI provides no corroboration,
    # the SAR window is systematically compromised (snow/ice/frozen ground, terrain specular).
    # Used in two places: (1) flood scoring -- veto acute_score (threshold scales down with
    # snow artifact risk from climate/elevation); (2) active_flood -- block strong-anomaly bypass.
    SAR_CHRONIC_ARTIFACT_THRESHOLD: float = 0.50
    # Secondary lower threshold for vetoing acute_score when NDWI is confirmed zero.
    # If NDWI wetness persistence is exactly 0.0 (optical never saw surface water across 5 years)
    # AND SAR chronic exceeds this fraction, the combination is a strong orbit geometry artifact
    # fingerprint (e.g. valley walls or smooth terrain producing specular C-band returns on one
    # orbit track). The strict NDWI=0 requirement prevents suppressing genuine episodic floods
    # on normally-dry lowland sites where NDWI may be absent only in calm conditions.
    SAR_ZERO_NDWI_ARTIFACT_THRESHOLD: float = 0.12

    # active_flood corroboration: acute SAR anomaly alone is not sufficient to flag
    # active_flood -- SAR slope artifacts (single orbit on snow/rock) can mimic water.
    # Require independent corroboration: optical (NDWI) or very strong anomaly.
    # SAR chronic (sar_water_freq) is NOT used: it can share the same look-angle artifact,
    # creating circular corroboration.
    SAR_ACTIVE_FLOOD_MIN_NDWI: float = 0.08      # >= ~1 month/year optical water history
    SAR_ACTIVE_FLOOD_STRONG_ANOMALY: float = 0.35  # very strong anomaly -- flag regardless

    # Standardized window size for all raster reads
    COG_WINDOW_SIZE: int = 64
    S2_PIXEL_SIZE_M: float = 10.0  # Sentinel-2 native pixel size (m); defines the 640 m analysis footprint

    # Scene selection
    MAX_SCENES_PER_MONTH: int = 2
    MAX_TOTAL_SCENES: int = 120
    # Maximum items fetched from STAC per search. Must be large enough to cover
    # the full date range regardless of scene density (MPC returns newest-first
    # by default, so a low cap silently drops older months). At 10 scenes/month
    # over 5 years = 600 scenes; 2000 gives comfortable headroom.
    STAC_MAX_ITEMS: int = 2000

    # Geometry limits
    MAX_PARCEL_AREA_SQM: float = 5_000_000.0  # 500 ha
    MAX_VERTICES: int = 5000
    COORD_PRECISION: int = 7
    DEFAULT_POINT_BUFFER_M: float = 100.0

    # COG reading
    # S3 can handle high concurrency; 32 is a reasonable ceiling before bandwidth
    # saturation on a server instance. Previously 8, which serialised too aggressively.
    MAX_CONCURRENT_COG_READS: int = 32

    # Rate limiting
    DAILY_LOCATION_LIMIT: int = 5  # max new locations per user per UTC day (free plan)

    # Cache
    CACHE_TTL_SECONDS: int = 604_800  # 7 days

    # NOAA CO-OPS tidal station proximity
    TIDAL_ZONE_RADIUS_KM: float = 30.0      # Max distance to nearest tidal station to classify as tidal zone
    TIDAL_ZONE_MAX_ELEV_M: float = 10.0     # Elevation gate: above this, tidal influence is impossible
    NOAA_STATION_REFRESH_DAYS: int = 30     # Re-fetch station list this many days after last update

    # SAR slope masking (DEM-derived flat-terrain filter)
    # Pixels with slope >= this threshold are excluded from the SAR water fraction
    # denominator. Rocky/snowy hillsides at steep angles produce low-DN C-band
    # returns that mimic open water -- masking them corrects the water fraction
    # without touching the snow or burn suppression logic.
    DEM_FLAT_SLOPE_THRESHOLD: float = 15.0  # degrees

    # Versions
    PROCESSING_VERSION: str = "s2l2a-v1.36.0"
    SCORE_VERSION: str = "risk-v1.20.3"

    # Trend-aware scoring -- Part A: active episode multipliers
    ACTIVE_FLOOD_BOOST: float = 1.40
    ACTIVE_DROUGHT_BOOST: float = 1.30
    ACTIVE_FIRE_BOOST: float = 1.25

    # Trend-aware scoring -- Part B: 1y vs 5y momentum amplifiers / dampeners
    # Progressive worsening: ratio 2.0 → +12%, ratio 3.0 → +36%, ratio ≥ 4.2 → +50% (cap)
    # (rate doubles above 2× to reflect accelerating risk)
    # Improving: ratio 0.5 → -6%, ratio 0.0 → -12% (damp cap, asymmetric vs amp cap)
    MOMENTUM_AMP_MAX: float = 0.50    # cap on fractional amplitude boost (= +50%)
    MOMENTUM_AMP_SCALE: float = 0.12  # base rate per unit of excess ratio; doubles above 2×
    MOMENTUM_DAMP_MAX: float = 0.20   # cap on fractional dampening (= -20%)
    # When any relevant momentum ratio exceeds this threshold, recent trajectory
    # dominates and improving-slope mitigations are suppressed for that sub-score.
    MOMENTUM_PRIORITY_THRESHOLD: float = 1.5

    # Trend-aware scoring -- Part C: Theil-Sen slope sub-components
    NDWI_TREND_WET_MIN: float = 0.02      # NDWI slope (index/yr) → 100 pts wetness
    NDMI_TREND_STRESS_MAX: float = -0.05  # most-negative NDMI slope → 100 pts drought
    VPD_TREND_HIGH_MIN: float = 0.05      # VPD slope (kPa/yr) → 100 pts heat stress
    PDSI_TREND_DROUGHT_MAX: float = -0.5  # most-negative PDSI slope → 100 pts drought

    # Storage
    POSTGRES_DSN: str = "postgresql://postgres:postgres@localhost:5432/remotesensing"

    # Auth
    SECRET_KEY: str = ""                 # required in production -- set via env var
    JWT_EXPIRE_DAYS: int = 90

    # Email (Resend)
    RESEND_API_KEY: str = ""
    EMAIL_FROM_DOMAIN: str = "geomermaids.com"
    ADMIN_NOTIFY_EMAIL: str = ""         # if set, receives a notification on every new user registration
    FRONTEND_URL: str = ""               # e.g. https://climate-dashboard.geomermaids.com -- redirect after verification
    API_BASE_URL: str = ""               # e.g. https://climate.geomermaids.com -- used to build verify link in emails

    # Timeouts
    REQUEST_TIMEOUT_SECONDS: int = 60

    # Urban detection thresholds
    URBAN_BSI_FREQ_THRESHOLD: float = 0.50  # fraction of months with BSI > 0 (impervious signal)
    URBAN_BSI_FREQ_STRONG_THRESHOLD: float = 0.65  # high-confidence impervious signal alone (e.g. tropical cities with vegetation)
    URBAN_NDVI_THRESHOLD: float = 0.25
    URBAN_CANOPY_THRESHOLD: float = 0.25
    URBAN_MIN_NDVI_THRESHOLD: float = 0.06  # below this = naturally barren (desert/alpine rock, NDVI 0.01-0.04); dense urban cores can reach ~0.08
    URBAN_BSI_STRONG_MAX_CANOPY: float = 0.45  # Path 1 ceiling: vineyards/orchards have BSI > 65% + NDVI > 0.25 but canopy > 0.45; no city reaches this
    URBAN_BUILDING_FRACTION_THRESHOLD: float = 0.10  # Overture: > 10% building coverage → urban
    URBAN_BUILDING_FRACTION_VETO: float = 0.02       # Overture: < 2% building coverage → not urban (suppresses BSI spectral paths)

    # Scoring thresholds
    NDVI_ANOMALY_THRESHOLD: float = 0.1
    NDWI_WET_THRESHOLD: float = 0.0
    NDMI_STRESS_THRESHOLD: float = 0.0    # NDMI below → vegetation moisture stress
    NBR_BURN_THRESHOLD: float = 0.1       # absolute NBR below → burn signal (used for chart bar color only)
    NBR_ANOMALY_THRESHOLD: float = 0.15   # NBR must drop this far below seasonal climatology to count as fire anomaly
    # Minimum consecutive months of NBR anomaly required to count as a genuine
    # fire event. Applies to nbr_burn_freq_5y, SAR burn suppression, and chart
    # annotation -- all three now use anomaly-based detection so Mediterranean
    # dry seasons (naturally low NBR, zero anomaly) never trigger.
    NBR_MIN_CONSECUTIVE: int = 3
    NDSI_SNOW_THRESHOLD: float = 0.4      # NDSI above → snow-covered
    BSI_BARE_THRESHOLD: float = 0.0       # BSI above → bare soil exposed

    # TerraClimate (University of Idaho Climatology Lab -- THREDDS OPeNDAP)
    TERRACLIMATE_THREDDS_URL: str = "https://thredds.northwestknowledge.net:443/thredds/dodsC/TERRACLIMATE_ALL/data"
    TERRACLIMATE_VARIABLES: list[str] = ["tmax", "tmin", "ppt", "vpd", "PDSI"]
    TERRACLIMATE_VPD_HIGH_THRESHOLD: float = 1.5     # kPa
    TERRACLIMATE_PDSI_DROUGHT_THRESHOLD: float = -2.0
    TERRACLIMATE_TMAX_ANOMALY_SIGMA: float = 1.0     # stdevs above monthly mean

    # Terrain risk scoring thresholds (DTM derived: 3DEP for US, GLO-30 globally)
    TERRAIN_LANDSLIDE_SLOPE_MAX: float = 25.0     # slope_deg mapped to 100 for landslide score
    TERRAIN_LANDSLIDE_RELIEF_MAX: float = 300.0   # elevation_range_m mapped to 100
    TERRAIN_FLASH_ELEV_MAX: float = 300.0         # elevation_m above which terrain flash = 0
    TERRAIN_FLASH_SLOPE_MIN: float = 3.0          # minimum slope_deg for flash flood terrain
    TERRAIN_FLASH_SLOPE_MAX: float = 20.0         # slope_deg mapped to 1.0 for flash factor
    TERRAIN_DROUGHT_SLOPE_MIN: float = 10.0       # slope_deg threshold for drought amplifier
    TERRAIN_DROUGHT_AMP_MAX: float = 0.20         # max drought amplification (+20%)

    # Terrain HLI thresholds (heat load index amplifier for drought + heat stress)
    TERRAIN_HLI_THRESHOLD: float = 0.05      # minimum HLI to activate amplifier
    TERRAIN_HLI_AMP_MAX: float = 0.25        # max amplification (+25%)
    TERRAIN_HLI_FACTOR: float = 0.5          # HLI × factor = raw amplification fraction

    # Terrain TPI flood boost (valley floor detection)
    TERRAIN_TPI_FLOOD_THRESHOLD: float = -5.0    # m; depressions deeper than this get boost
    TERRAIN_TPI_FLOOD_MAX_BOOST: float = 20.0    # max +20 pts

    # Terrain curvature flood boost (concave terrain)
    # Sign convention: positive = concave (valley), negative = convex (ridge)
    TERRAIN_CURVATURE_THRESHOLD: float = 0.0001   # m⁻¹; concavity threshold (positive)
    TERRAIN_CURVATURE_MAX_BOOST: float = 10.0     # max +10 pts
    TERRAIN_CURVATURE_SCALE: float = 50000.0      # curvature × scale = raw boost (before cap)

    # Growing season (latitude threshold for zone split)
    GROWING_SEASON_LAT_THRESHOLD: float = 33.0
    TEMPERATE_SEASON_MONTHS: list[int] = [5, 6, 7, 8, 9]
    SUBTROPICAL_SEASON_MONTHS: list[int] = [3, 4, 5, 6, 7, 8, 9, 10, 11]

    # SCL valid classes
    # 2=Dark area pixels (dark vegetation/shadow edges -- valid land signal)
    # 4=Vegetation, 5=Bare soils, 6=Water, 7=Unclassified (low cloud prob)
    # 11=Snow/Ice -- valid land surface, not a cloud artifact; required for NDSI
    SCL_VALID_CLASSES: list[int] = [2, 4, 5, 6, 7, 11]

    # Minimum valid pixel fraction to accept an observation.
    # 0.05 salvages partial clear windows in persistently cloudy regions.
    MIN_VALID_PIXEL_FRACTION: float = 0.05

    # CORS
    CORS_ORIGINS: list[str] = [
        "http://localhost",
        "http://localhost:3000",
        "http://localhost:8000",
        "https://climate-dashboard.geomermaids.com",
        "https://location-sentinel.pages.dev",
    ]

    # Thumbnails / Mapbox
    THUMBNAIL_WIDTH: int = 300
    THUMBNAIL_HEIGHT: int = 200
    THUMBNAIL_CACHE_TTL: int = 86400  # 1 day
    GEOJSON_IO_MAX_URL_LENGTH: int = 8000
    MAPBOX_TOKEN: str = "pk.eyJ1IjoiZ21lcm1haWRzIiwiYSI6ImNtZDBlanQ5bTE5czAycXMzNnF0Z3dodHEifQ.CXbfNM-wVW4UORDm65mE2Q"
    MAPBOX_STYLE: str = "mapbox/satellite-v9"
    THUMBNAIL_CONTEXT_BUFFER_M: float = 400.0  # extra buffer around analysis geometry (~1000m viewport for point inputs)


settings = Settings()
