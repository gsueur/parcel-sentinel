from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    model_config = {"env_prefix": "", "case_sensitive": True}

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
    SAR_MAX_SCENES_PER_MONTH: int = 2
    SAR_MAX_TOTAL_SCENES: int = 120

    # Standardized window size for all raster reads
    COG_WINDOW_SIZE: int = 64

    # Scene selection
    MAX_SCENES_PER_MONTH: int = 2
    MAX_TOTAL_SCENES: int = 120

    # Geometry limits
    MAX_PARCEL_AREA_SQM: float = 5_000_000.0  # 500 ha
    MAX_VERTICES: int = 5000
    COORD_PRECISION: int = 7
    DEFAULT_POINT_BUFFER_M: float = 100.0

    # COG reading
    MAX_CONCURRENT_COG_READS: int = 8

    # Cache
    CACHE_TTL_SECONDS: int = 604_800  # 7 days

    # Versions
    PROCESSING_VERSION: str = "s2l2a-v1.4.0"
    SCORE_VERSION: str = "risk-v1.3.0"

    # Storage
    DUCKDB_PATH: str = "location_sentinel.duckdb"

    # Timeouts
    REQUEST_TIMEOUT_SECONDS: int = 60

    # Urban detection thresholds
    URBAN_BSI_FREQ_THRESHOLD: float = 0.50  # fraction of months with BSI > 0 (impervious signal)
    URBAN_BSI_FREQ_STRONG_THRESHOLD: float = 0.65  # high-confidence impervious signal alone (e.g. tropical cities with vegetation)
    URBAN_NDVI_THRESHOLD: float = 0.25
    URBAN_CANOPY_THRESHOLD: float = 0.25

    # Scoring thresholds
    NDVI_ANOMALY_THRESHOLD: float = 0.1
    NDWI_WET_THRESHOLD: float = 0.0
    NDMI_STRESS_THRESHOLD: float = 0.0    # NDMI below → vegetation moisture stress
    NBR_BURN_THRESHOLD: float = 0.1       # NBR below → burn signal present
    NDSI_SNOW_THRESHOLD: float = 0.4      # NDSI above → snow-covered
    BSI_BARE_THRESHOLD: float = 0.0       # BSI above → bare soil exposed

    # Growing season (latitude threshold for zone split)
    GROWING_SEASON_LAT_THRESHOLD: float = 33.0
    TEMPERATE_SEASON_MONTHS: list[int] = [5, 6, 7, 8, 9]
    SUBTROPICAL_SEASON_MONTHS: list[int] = [3, 4, 5, 6, 7, 8, 9, 10, 11]

    # SCL valid classes
    # 4=Vegetation, 5=Bare soils, 6=Water, 7=Unclassified (low cloud prob)
    # 11=Snow/Ice -- included because snow is a valid land surface observation,
    # not a cloud artifact. Excluding it would mask winter scenes and zero-out NDSI.
    SCL_VALID_CLASSES: list[int] = [4, 5, 6, 7, 11]

    # Minimum valid pixel fraction to accept an observation
    MIN_VALID_PIXEL_FRACTION: float = 0.1

    # Thumbnails / Mapbox
    THUMBNAIL_WIDTH: int = 300
    THUMBNAIL_HEIGHT: int = 200
    THUMBNAIL_CACHE_TTL: int = 86400  # 1 day
    GEOJSON_IO_MAX_URL_LENGTH: int = 8000
    MAPBOX_TOKEN: str = "pk.eyJ1IjoiZ21lcm1haWRzIiwiYSI6ImNtZDBlanQ5bTE5czAycXMzNnF0Z3dodHEifQ.CXbfNM-wVW4UORDm65mE2Q"
    MAPBOX_STYLE: str = "mapbox/streets-v11"
    THUMBNAIL_CONTEXT_BUFFER_M: float = 400.0  # extra buffer around analysis geometry (~1000m viewport for point inputs)


settings = Settings()
