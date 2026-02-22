from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    model_config = {"env_prefix": "", "case_sensitive": True}

    # Logging
    LOG_LEVEL: str = "INFO"

    # STAC
    STAC_ENDPOINTS: str = "https://earth-search.aws.element84.com/v1"
    STAC_COLLECTION: str = "sentinel-2-l2a"

    # AWS COG source (public bucket, no auth)
    AWS_SENTINEL_BUCKET: str = "sentinel-cogs"
    AWS_SENTINEL_REGION: str = "us-west-2"

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
    PROCESSING_VERSION: str = "s2l2a-v1.2.0"
    SCORE_VERSION: str = "risk-v1.1.0"

    # Storage
    DUCKDB_PATH: str = "location_sentinel.duckdb"

    # Timeouts
    REQUEST_TIMEOUT_SECONDS: int = 60

    # Urban detection thresholds
    URBAN_BSI_THRESHOLD: float = 0.08
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
    SCL_VALID_CLASSES: list[int] = [4, 5, 6, 7]

    # Minimum valid pixel fraction to accept an observation
    MIN_VALID_PIXEL_FRACTION: float = 0.1

    # Thumbnails / Mapbox
    THUMBNAIL_WIDTH: int = 300
    THUMBNAIL_HEIGHT: int = 200
    THUMBNAIL_CACHE_TTL: int = 86400  # 1 day
    GEOJSON_IO_MAX_URL_LENGTH: int = 8000
    MAPBOX_TOKEN: str = "pk.eyJ1IjoiZ21lcm1haWRzIiwiYSI6ImNtZDBlanQ5bTE5czAycXMzNnF0Z3dodHEifQ.CXbfNM-wVW4UORDm65mE2Q"
    MAPBOX_STYLE: str = "mapbox/streets-v11"
    THUMBNAIL_CONTEXT_BUFFER_M: float = 1500.0  # extra buffer for landscape context around the location


settings = Settings()
