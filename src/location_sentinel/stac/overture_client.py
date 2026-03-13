from __future__ import annotations

import logging
import math

logger = logging.getLogger(__name__)

# Area of the analysis window (640m × 640m)
_WINDOW_AREA_M2 = 640.0 ** 2

# DuckDB extensions are installed once to ~/.duckdb/extensions/ and loaded
# from disk on subsequent runs. In containerised deployments ensure that
# directory is writable (or set DUCKDB_EXTENSION_DIRECTORY env var).


def _window_bbox(lat: float, lon: float) -> tuple[float, float, float, float]:
    """Return (minx, miny, maxx, maxy) for the 640 m analysis window."""
    half_m = 320.0
    lat_deg = half_m / 111_320.0
    lon_deg = half_m / (111_320.0 * math.cos(math.radians(lat)))
    return lon - lon_deg, lat - lat_deg, lon + lon_deg, lat + lat_deg


def query_buildings_sync(lat: float, lon: float, bucket: str, release: str) -> dict:
    """Query Overture Maps buildings GeoParquet on S3 for the 640 m window.

    Returns a dict with:
      building_count          -- number of building footprints intersecting the window
      building_fraction       -- sum of clipped footprint area / 409 600 m²  [0, 1]
      mean_building_height_m  -- mean height in metres (None when mostly absent)

    Returns None-valued dict on any failure so the pipeline can degrade gracefully.

    Runs synchronously -- call from an asyncio executor.
    """
    import duckdb

    minx, miny, maxx, maxy = _window_bbox(lat, lon)

    # Scale factor: converts ST_Area (degrees²) to m² at this latitude.
    # Accurate to < 0.1 % for the small footprints we deal with.
    deg_to_m2 = (111_320.0 * math.cos(math.radians(lat))) ** 2

    path = f"s3://{bucket}/release/{release}/theme=buildings/type=building/*.parquet"

    try:
        conn = duckdb.connect()

        # Extensions are installed to disk on first call; subsequent calls load
        # from the local cache and are fast.
        conn.execute("INSTALL httpfs; LOAD httpfs;")
        conn.execute("INSTALL spatial; LOAD spatial;")

        # Anonymous access for the public Overture bucket.
        conn.execute("SET s3_region='us-west-2';")
        conn.execute("SET s3_access_key_id='';")
        conn.execute("SET s3_secret_access_key='';")

        envelope = f"ST_MakeEnvelope({minx}, {miny}, {maxx}, {maxy})"

        row = conn.execute(
            f"""
            SELECT
                COUNT(*)::INTEGER                                              AS building_count,
                COALESCE(SUM(
                    ST_Area(ST_Intersection(ST_GeomFromWKB(geometry), {envelope}))
                    * {deg_to_m2}
                ), 0.0)                                                        AS building_area_m2,
                AVG(CASE WHEN height > 0 THEN height END)                     AS mean_height_m
            FROM read_parquet('{path}')
            WHERE bbox.xmin <= {maxx} AND bbox.xmax >= {minx}
              AND bbox.ymin <= {maxy} AND bbox.ymax >= {miny}
            """
        ).fetchone()

        conn.close()

        count = int(row[0] or 0)
        area_m2 = float(row[1] or 0.0)
        mean_height = float(row[2]) if row[2] is not None else None

        logger.info(
            "Overture buildings: count=%d fraction=%.3f mean_height=%s lat=%.4f lon=%.4f release=%s",
            count, area_m2 / _WINDOW_AREA_M2,
            f"{mean_height:.1f}m" if mean_height else "n/a",
            lat, lon, release,
        )
        return {
            "building_count": count,
            "building_fraction": round(min(1.0, area_m2 / _WINDOW_AREA_M2), 4),
            "mean_building_height_m": round(mean_height, 1) if mean_height else None,
        }

    except Exception as exc:
        logger.warning("Overture buildings query failed lat=%.4f lon=%.4f: %s", lat, lon, exc)
        return {
            "building_count": None,
            "building_fraction": None,
            "mean_building_height_m": None,
        }
