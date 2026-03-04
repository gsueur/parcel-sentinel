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

# GLO-30 is 1 arc-second resolution.
# 1 arc-second latitude  ≈ 30.87 m (constant)
# 1 arc-second longitude ≈ 30.87 * cos(lat) m (varies with latitude)
_ARC_SEC_M = 30.87


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


def read_dem_sync(lat: float, lon: float) -> dict[str, float] | None:
    """Read a 64×64 elevation window from Copernicus GLO-30 via /vsis3/.

    Returns a dict with:
      elevation_m        -- mean elevation of the window (metres, WGS84 ellipsoidal)
      elevation_range_m  -- max-min within the window (terrain relief proxy)
      slope_deg          -- mean slope angle (degrees) derived from numpy gradient

    Returns None on any read failure (tile missing, outside coverage, etc.).
    Runs synchronously -- call from an asyncio executor.
    """
    import rasterio
    from rasterio.windows import Window

    path = _tile_path(lat, lon)
    size = settings.COG_WINDOW_SIZE  # 64

    try:
        with rasterio.Env(**_GDAL_ENV):
            with rasterio.open(path) as src:
                # rasterio.index returns (row, col) for a (lon, lat) point
                row_c, col_c = src.index(lon, lat)

                col_off = max(0, col_c - size // 2)
                row_off = max(0, row_c - size // 2)
                col_end = min(src.width,  col_off + size)
                row_end = min(src.height, row_off + size)

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
            logger.warning("DEM: <25%% valid pixels at (%.4f, %.4f), skipping", lat, lon)
            return None

        elev_m = float(np.nanmean(data))
        elev_range_m = float(np.nanmax(data) - np.nanmin(data))

        # Slope from central differences.
        # np.gradient(data) returns [grad_row, grad_col] in units of elev/pixel.
        # Convert to m/m: divide by pixel size in metres.
        pixel_lat_m = _ARC_SEC_M
        pixel_lon_m = _ARC_SEC_M * math.cos(math.radians(lat))
        grad_row, grad_col = np.gradient(np.nan_to_num(data, nan=elev_m))
        dz_dy = grad_row / pixel_lat_m  # dimensionless (m/m) north-south
        dz_dx = grad_col / pixel_lon_m  # dimensionless (m/m) east-west
        slope_deg = float(np.degrees(np.arctan(np.sqrt(dz_dx**2 + dz_dy**2))).mean())

        logger.info(
            "DEM read OK path=%.80s elev=%.1f m range=%.1f m slope=%.2f°",
            path, elev_m, elev_range_m, slope_deg,
        )
        return {
            "elevation_m": round(elev_m, 1),
            "elevation_range_m": round(elev_range_m, 1),
            "slope_deg": round(slope_deg, 2),
        }

    except Exception as exc:
        logger.warning("DEM read failed path=%.80s err=%s", path, exc)
        return None
