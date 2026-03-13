from __future__ import annotations

import logging
import math

import numpy as np

from ..config import settings

logger = logging.getLogger(__name__)

_GDAL_ENV = {
    "AWS_NO_SIGN_REQUEST": "YES",
    "AWS_REGION": settings.DEM_AWS_REGION,
    "GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR",
    "CPL_VSIL_CURL_ALLOWED_EXTENSIONS": ".tif,.tiff",
}

# 3DEP tiles are in us-west-2; inherit all other GLO-30 env settings.
_GDAL_ENV_3DEP = {**_GDAL_ENV, "AWS_REGION": settings.DEM_3DEP_REGION}

# GLO-30 / 3DEP are both ~1 arc-second resolution.
# 1 arc-second latitude  ≈ 30.87 m (constant)
# 1 arc-second longitude ≈ 30.87 * cos(lat) m (varies with latitude)
_ARC_SEC_M = 30.87

# Continental US + Alaska + Hawaii bounding box
_US_LAT_MIN, _US_LAT_MAX = 18.0, 72.0
_US_LON_MIN, _US_LON_MAX = -180.0, -64.0


def _is_us(lat: float, lon: float) -> bool:
    return _US_LAT_MIN <= lat <= _US_LAT_MAX and _US_LON_MIN <= lon <= _US_LON_MAX


def _tile_path(lat: float, lon: float) -> str:
    """Return the /vsis3/ path for the GLO-30 1°×1° tile containing (lat, lon).

    Tile grid: floors lat/lon to integer degree.  Hemisphere letters: N/S, E/W.
    Example: lat=38.9, lon=-77.0  →  N38_00_W077_00
    """
    lat_tile = int(math.floor(lat))
    lon_tile = int(math.floor(lon))
    lat_hem = "N" if lat_tile >= 0 else "S"
    lon_hem = "E" if lon_tile >= 0 else "W"
    name = (
        f"Copernicus_DSM_COG_10"
        f"_{lat_hem}{abs(lat_tile):02d}_00"
        f"_{lon_hem}{abs(lon_tile):03d}_00_DEM"
    )
    return f"/vsis3/{settings.DEM_AWS_BUCKET}/{name}/{name}.tif"


def _tile_path_3dep(lat: float, lon: float) -> str:
    """Return the /vsis3/ path for a USGS 3DEP 1" tile containing (lat, lon).

    Bucket: prd-tnm (public, no auth, us-west-2)
    Pattern: n{lat}w{lon}/USGS_1_n{lat}w{lon}.tif  (lowercase, 2-digit lat, 3-digit lon)
    Example: lat=38.9, lon=-77.0  →  n38w077/USGS_1_n38w077.tif
    """
    lat_tile = int(math.floor(lat))
    lon_tile = int(math.floor(lon))
    lat_hem = "n" if lat_tile >= 0 else "s"
    lon_hem = "w" if lon_tile <= 0 else "e"
    tag = f"{lat_hem}{abs(lat_tile):02d}{lon_hem}{abs(lon_tile):03d}"
    return f"/vsis3/{settings.DEM_3DEP_BUCKET}/StagedProducts/Elevation/1/TIFF/current/{tag}/USGS_1_{tag}.tif"


def _read_dem_from_path(
    path: str, lat: float, lon: float, gdal_env: dict
) -> dict[str, float] | None:
    """Read a 64×64 elevation window from a COG at *path* via /vsis3/.

    Returns the same feature dict as read_dem_sync, or None on any failure.
    """
    import rasterio
    from rasterio.windows import Window

    size = settings.COG_WINDOW_SIZE  # 64 — output pixel count (matches S2)

    pixel_lat_m = _ARC_SEC_M
    pixel_lon_m = _ARC_SEC_M * math.cos(math.radians(lat))
    s2_footprint_m = size * settings.S2_PIXEL_SIZE_M  # 640 m
    dem_native = max(4, round(s2_footprint_m / pixel_lat_m))  # ~21 at mid-latitudes

    eff_lat_m = s2_footprint_m / size   # ≈ 10 m
    eff_lon_m = (dem_native * pixel_lon_m) / size

    try:
        with rasterio.Env(**gdal_env):
            with rasterio.open(path) as src:
                row_c, col_c = src.index(lon, lat)

                col_off = max(0, col_c - dem_native // 2)
                row_off = max(0, row_c - dem_native // 2)
                col_end = min(src.width,  col_off + dem_native)
                row_end = min(src.height, row_off + dem_native)

                window = Window(col_off, row_off, col_end - col_off, row_end - row_off)
                data = src.read(
                    1, window=window,
                    out_shape=(size, size),
                    resampling=rasterio.enums.Resampling.bilinear,
                ).astype(np.float32)

                nodata = src.nodata
                if nodata is not None:
                    data[data == nodata] = np.nan

        valid = data[~np.isnan(data)]
        if len(valid) < size * size * 0.25:
            logger.warning("DEM: <25%% valid pixels at (%.4f, %.4f) path=%.80s", lat, lon, path)
            return None

        elev_m = float(np.nanmean(data))
        elev_min_m = float(np.nanmin(data))
        elev_max_m = float(np.nanmax(data))
        elev_range_m = elev_max_m - elev_min_m

        # Slope from central differences.
        # np.gradient(data) returns [grad_row, grad_col] in units of elev/pixel.
        # Convert to m/m using the effective pixel size of the resampled 64×64 grid.
        grad_row, grad_col = np.gradient(np.nan_to_num(data, nan=elev_m))
        dz_dy = grad_row / eff_lat_m  # dimensionless (m/m) north-south
        dz_dx = grad_col / eff_lon_m  # dimensionless (m/m) east-west
        slope_deg = float(np.degrees(np.arctan(np.sqrt(dz_dx**2 + dz_dy**2))).mean())

        # Aspect: circular mean downslope direction (0=N, clockwise)
        aspect_pixel = (np.degrees(np.arctan2(-dz_dx, dz_dy)) + 360) % 360
        sin_a = np.nanmean(np.sin(np.radians(aspect_pixel)))
        cos_a = np.nanmean(np.cos(np.radians(aspect_pixel)))
        aspect_deg = float((np.degrees(np.arctan2(sin_a, cos_a)) + 360) % 360)

        # TPI: center pixel vs window mean (positive = ridge, negative = valley)
        cy, cx = size // 2, size // 2
        tpi_m = float(data[cy, cx] - elev_m)

        # Curvature: Laplacian at the center point using a 5×5 kernel.
        # Sign convention: positive = concave (valley/bowl, collects water);
        # negative = convex (ridge/dome, sheds water).
        d2z_dy2 = np.gradient(dz_dy, axis=0) / eff_lat_m
        d2z_dx2 = np.gradient(dz_dx, axis=1) / eff_lon_m
        laplacian = d2z_dy2 + d2z_dx2
        cy, cx = size // 2, size // 2
        r = 2  # 5×5 neighbourhood ≈ 50 m × 50 m
        curvature = float(np.nanmean(laplacian[cy - r:cy + r + 1, cx - r:cx + r + 1]))

        # Heat Load Index (solar radiation proxy, 0–~0.8)
        equatorial_dir = 180.0 if lat >= 0 else 0.0
        heat_load_index = float(
            (1.0 - np.cos(np.radians(aspect_deg - equatorial_dir))) / 2.0
            * np.sin(np.radians(slope_deg))
        )

        # Raw array bytes for DEM PNG (stored in DB, filtered from features dict)
        elevation_array = data.astype(np.float32).tobytes()

        logger.info(
            "DEM read OK path=%.80s elev=%.1f m range=%.1f m slope=%.2f° aspect=%.0f° tpi=%.1f m",
            path, elev_m, elev_range_m, slope_deg, aspect_deg, tpi_m,
        )
        return {
            "elevation_m":       round(elev_m, 1),
            "elevation_min_m":   round(elev_min_m, 1),
            "elevation_max_m":   round(elev_max_m, 1),
            "elevation_range_m": round(elev_range_m, 1),
            "slope_deg":         round(slope_deg, 2),
            "aspect_deg":        round(aspect_deg, 1),
            "tpi_m":             round(tpi_m, 2),
            "curvature":         curvature,
            "heat_load_index":   round(heat_load_index, 4),
            "elevation_array":   elevation_array,
        }

    except Exception as exc:
        logger.warning("DEM read failed path=%.80s err=%s", path, exc)
        return None


def read_dem_sync(lat: float, lon: float) -> dict[str, float] | None:
    """Read a 64×64 elevation window from the best available bare-earth DEM via /vsis3/.

    Source priority:
      1. USGS 3DEP 1" (true lidar DTM) -- US locations only
      2. Copernicus GLO-30 (DSM fallback) -- global

    Returns None if all sources fail (tile missing, outside coverage, etc.).
    Runs synchronously -- call from an asyncio executor.
    """
    candidates: list[tuple[str, dict]] = []
    if _is_us(lat, lon):
        candidates.append((_tile_path_3dep(lat, lon), _GDAL_ENV_3DEP))
    candidates.append((_tile_path(lat, lon), _GDAL_ENV))

    for path, env in candidates:
        result = _read_dem_from_path(path, lat, lon, env)
        if result is not None:
            return result
    return None
