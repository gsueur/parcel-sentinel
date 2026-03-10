from __future__ import annotations

import dataclasses
import json
import logging
import math
import os
import secrets
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import numpy as np
import psycopg2
import psycopg2.extras
import psycopg2.pool
from shapely.geometry import shape

from ..config import settings

# ---------------------------------------------------------------------------
# Koeppen-Geiger climate classification metadata
# ---------------------------------------------------------------------------
_KG_DESCRIPTIONS: dict[str, tuple[str, str]] = {
    "Af":  ("Tropical rainforest climate",                                            "Pmin ≥ 60 mm/month"),
    "Am":  ("Tropical monsoon climate",                                               "Pann ≥ 25(100−Pmin)"),
    "As":  ("Tropical dry savanna climate",                                           "Pmin < 60 mm in summer"),
    "Aw":  ("Tropical savanna climate (wet)",                                         "Pmin < 60 mm in winter"),
    "BWh": ("Hot desert climate",                                                     "Pann ≤ 5 Pth, Tann ≥ +18 °C"),
    "BWk": ("Cold desert climate",                                                    "Pann ≤ 5 Pth, Tann < +18 °C"),
    "BSh": ("Hot semi-arid (steppe) climate",                                         "5 Pth < Pann ≤ 10 Pth, Tann ≥ +18 °C"),
    "BSk": ("Cold semi-arid (steppe) climate",                                        "5 Pth < Pann ≤ 10 Pth, Tann < +18 °C"),
    "Cfa": ("Humid subtropical climate",                                              "No dry season, Thot ≥ +22 °C"),
    "Cfb": ("Temperate oceanic climate",                                              "No dry season, 4+ months ≥ +10 °C, Thot < +22 °C"),
    "Cfc": ("Subpolar oceanic climate",                                               "No dry season, 1–3 months ≥ +10 °C"),
    "Csa": ("Hot-summer Mediterranean climate",                                       "Dry summer, Thot ≥ +22 °C"),
    "Csb": ("Warm-summer Mediterranean climate",                                      "Dry summer, Thot < +22 °C, 4+ months ≥ +10 °C"),
    "Csc": ("Cool-summer Mediterranean climate",                                      "Dry summer, 1–3 months ≥ +10 °C"),
    "Cwa": ("Monsoon-influenced humid subtropical climate",                           "Dry winter, Thot ≥ +22 °C"),
    "Cwb": ("Subtropical highland / oceanic climate with dry winters",                "Dry winter, Thot < +22 °C, 4+ months ≥ +10 °C"),
    "Cwc": ("Cold subtropical highland / subpolar oceanic climate with dry winters",  "Dry winter, 1–3 months ≥ +10 °C"),
    "Dfa": ("Hot-summer humid continental climate",                                   "No dry season, Thot ≥ +22 °C"),
    "Dfb": ("Warm-summer humid continental climate",                                  "No dry season, Thot < +22 °C, 4+ months ≥ +10 °C"),
    "Dfc": ("Subarctic climate",                                                      "No dry season, 1–3 months ≥ +10 °C"),
    "Dfd": ("Extremely cold subarctic climate",                                       "No dry season, Tcold ≤ −38 °C"),
    "Dsa": ("Hot, dry-summer continental climate",                                    "Dry summer, Thot ≥ +22 °C"),
    "Dsb": ("Warm, dry-summer continental climate",                                   "Dry summer, Thot < +22 °C, 4+ months ≥ +10 °C"),
    "Dsc": ("Dry-summer subarctic climate",                                           "Dry summer, 1–3 months ≥ +10 °C"),
    "Dsd": ("Dry-summer extremely cold subarctic climate",                            "Dry summer, Tcold ≤ −38 °C"),
    "Dwa": ("Monsoon-influenced hot-summer humid continental climate",                "Dry winter, Thot ≥ +22 °C"),
    "Dwb": ("Monsoon-influenced warm-summer humid continental climate",               "Dry winter, Thot < +22 °C, 4+ months ≥ +10 °C"),
    "Dwc": ("Monsoon-influenced subarctic climate",                                   "Dry winter, 1–3 months ≥ +10 °C"),
    "Dwd": ("Monsoon-influenced extremely cold subarctic climate",                    "Dry winter, Tcold ≤ −38 °C"),
    "ET":  ("Tundra climate",                                                         "0 °C ≤ Thot < +10 °C"),
    "EF":  ("Ice cap climate",                                                        "Thot < 0 °C"),
}

_KG_MAIN: dict[str, str] = {
    "A": "Tropical",
    "B": "Arid",
    "C": "Temperate",
    "D": "Cold (continental)",
    "E": "Polar",
}


def _round_floats(obj, ndigits: int = 4):
    if isinstance(obj, float):
        return round(obj, ndigits)
    if isinstance(obj, dict):
        return {k: _round_floats(v, ndigits) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_round_floats(v, ndigits) for v in obj]
    return obj


def _snap_to_koeppen_grid(coord: float) -> float:
    return math.floor(coord / 0.5) * 0.5 + 0.25


def _frombuffer(val) -> np.ndarray:
    """Convert psycopg2 BYTEA result (memoryview or bytes) to numpy float32 array."""
    if isinstance(val, memoryview):
        return np.frombuffer(bytes(val), dtype=np.float32)
    return np.frombuffer(val, dtype=np.float32)


logger = logging.getLogger(__name__)


class PostgresStore:
    """PostgreSQL persistence layer replacing DuckDBStore."""

    def __init__(self, dsn: str = settings.POSTGRES_DSN):
        self._dsn = dsn
        self._pool: psycopg2.pool.ThreadedConnectionPool | None = None

    @contextmanager
    def _get_conn(self):
        assert self._pool is not None, "DB not connected"
        conn = self._pool.getconn()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            self._pool.putconn(conn)

    def connect(self) -> None:
        self._pool = psycopg2.pool.ThreadedConnectionPool(2, 20, dsn=self._dsn)
        self._create_tables()

    def close(self) -> None:
        if self._pool:
            self._pool.closeall()
            self._pool = None

    def _create_tables(self) -> None:
        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS location_features (
                    location_key VARCHAR NOT NULL,
                    processing_version VARCHAR NOT NULL,
                    date_start VARCHAR NOT NULL,
                    date_end VARCHAR NOT NULL,
                    features_json TEXT,
                    quality_json TEXT,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (location_key, processing_version, date_start, date_end)
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS location_timeseries (
                    location_key VARCHAR NOT NULL,
                    processing_version VARCHAR NOT NULL,
                    cadence VARCHAR NOT NULL,
                    metric VARCHAR NOT NULL,
                    series_json TEXT,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (location_key, processing_version, cadence, metric)
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS location_scores (
                    location_key VARCHAR NOT NULL,
                    score_version VARCHAR NOT NULL,
                    lookback_years INTEGER NOT NULL,
                    scores_json TEXT,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (location_key, score_version, lookback_years)
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS customers (
                    customer_id VARCHAR PRIMARY KEY,
                    name VARCHAR NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id VARCHAR(6) PRIMARY KEY,
                    email VARCHAR UNIQUE NOT NULL,
                    password_hash VARCHAR NOT NULL,
                    name VARCHAR,
                    role VARCHAR NOT NULL DEFAULT 'user',
                    is_verified BOOLEAN NOT NULL DEFAULT FALSE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS email_verification_tokens (
                    token VARCHAR PRIMARY KEY,
                    user_id VARCHAR(6) REFERENCES users(user_id) ON DELETE CASCADE,
                    expires_at TIMESTAMP NOT NULL,
                    used_at TIMESTAMP
                )
            """)
            # Drop the FK from location_geometries.customer_id → customers so that
            # user_ids (from the users table) can be stored there going forward.
            cur.execute("""
                ALTER TABLE location_geometries
                    DROP CONSTRAINT IF EXISTS location_geometries_customer_id_fkey
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS location_geometries (
                    location_key VARCHAR PRIMARY KEY,
                    geojson_text TEXT,
                    name VARCHAR,
                    customer_id VARCHAR REFERENCES customers(customer_id),
                    climate_code VARCHAR,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            # Add is_public column if it doesn't exist yet; use DEFAULT TRUE so all
            # pre-existing rows are immediately visible on the public landing page.
            cur.execute("""
                ALTER TABLE location_geometries
                    ADD COLUMN IF NOT EXISTS is_public BOOLEAN NOT NULL DEFAULT TRUE
            """)
            # After migration, new rows default to FALSE (private) unless explicitly set.
            cur.execute("""
                ALTER TABLE location_geometries
                    ALTER COLUMN is_public SET DEFAULT FALSE
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS scene_bands (
                    location_key VARCHAR NOT NULL,
                    scene_id VARCHAR NOT NULL,
                    month_key VARCHAR NOT NULL,
                    processing_version VARCHAR NOT NULL,
                    band_key VARCHAR NOT NULL,
                    width SMALLINT NOT NULL DEFAULT 64,
                    height SMALLINT NOT NULL DEFAULT 64,
                    data BYTEA NOT NULL,
                    cloud_fraction DOUBLE PRECISION,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (location_key, scene_id, processing_version, band_key)
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS sar_scene_bands (
                    location_key VARCHAR NOT NULL,
                    scene_id VARCHAR NOT NULL,
                    month_key VARCHAR NOT NULL,
                    processing_version VARCHAR NOT NULL,
                    width SMALLINT NOT NULL DEFAULT 64,
                    height SMALLINT NOT NULL DEFAULT 64,
                    vv_data BYTEA NOT NULL,
                    water_frac DOUBLE PRECISION,
                    rel_orbit SMALLINT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (location_key, scene_id, processing_version)
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS terraclimate_monthly (
                    grid_lat DOUBLE PRECISION NOT NULL,
                    grid_lon DOUBLE PRECISION NOT NULL,
                    variable VARCHAR NOT NULL,
                    year INTEGER NOT NULL,
                    month INTEGER NOT NULL,
                    value REAL,
                    PRIMARY KEY (grid_lat, grid_lon, variable, year, month)
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS noaa_tide_predictions (
                    station_id VARCHAR NOT NULL,
                    date VARCHAR NOT NULL,
                    hour INTEGER NOT NULL,
                    water_level_m REAL,
                    PRIMARY KEY (station_id, date, hour)
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS noaa_tidal_stations (
                    station_id VARCHAR PRIMARY KEY,
                    name VARCHAR,
                    lat DOUBLE PRECISION,
                    lon DOUBLE PRECISION,
                    state VARCHAR,
                    tide_type VARCHAR,
                    fetched_at VARCHAR
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS elevation_cache (
                    location_key    VARCHAR PRIMARY KEY,
                    elevation_m     REAL,
                    elevation_range_m REAL,
                    slope_deg       REAL,
                    elevation_min_m REAL,
                    elevation_max_m REAL,
                    aspect_deg      REAL,
                    tpi_m           REAL,
                    curvature       REAL,
                    heat_load_index REAL,
                    elevation_array BYTEA,
                    fetched_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS climate_descriptions (
                    code      VARCHAR PRIMARY KEY,
                    label     VARCHAR NOT NULL,
                    criterion VARCHAR
                )
            """)
            for code, (label, criterion) in _KG_DESCRIPTIONS.items():
                cur.execute(
                    """
                    INSERT INTO climate_descriptions (code, label, criterion)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (code) DO NOTHING
                    """,
                    [code, label, criterion],
                )
            cur.execute("""
                CREATE TABLE IF NOT EXISTS climates (
                    lat DOUBLE PRECISION NOT NULL,
                    lon DOUBLE PRECISION NOT NULL,
                    code VARCHAR NOT NULL,
                    PRIMARY KEY (lat, lon)
                )
            """)
            cur.execute("SELECT COUNT(*) FROM climates")
            count = cur.fetchone()[0]
            if count == 0:
                self._load_koeppen_file(cur)

    def _load_koeppen_file(self, cur) -> None:
        candidates = [
            os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "Koeppen-Geiger-ASCII.txt"),
            "Koeppen-Geiger-ASCII.txt",
        ]
        path = None
        for c in candidates:
            resolved = os.path.abspath(c)
            if os.path.exists(resolved):
                path = resolved
                break
        if path is None:
            logger.warning("Koeppen-Geiger-ASCII.txt not found; climates table will be empty")
            return

        logger.info("Loading Koeppen-Geiger data from %s", path)
        rows: list[tuple] = []
        with open(path, encoding="utf-8") as fh:
            next(fh)
            for line in fh:
                parts = line.split()
                if len(parts) < 3:
                    continue
                try:
                    lat, lon, code = float(parts[0]), float(parts[1]), parts[2]
                    rows.append((lat, lon, code))
                except ValueError:
                    continue

        psycopg2.extras.execute_values(
            cur,
            "INSERT INTO climates (lat, lon, code) VALUES %s ON CONFLICT (lat, lon) DO NOTHING",
            rows,
        )
        logger.info("Loaded %d Koeppen-Geiger grid cells", len(rows))

    def lookup_climate(self, lat: float, lon: float) -> str | None:
        if self._pool is None:
            return None
        snapped_lat = _snap_to_koeppen_grid(lat)
        snapped_lon = _snap_to_koeppen_grid(lon)
        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT code FROM climates WHERE lat = %s AND lon = %s",
                [snapped_lat, snapped_lon],
            )
            result = cur.fetchone()
        return result[0] if result else None

    def health_check(self) -> bool:
        try:
            if self._pool is None:
                return False
            with self._get_conn() as conn:
                conn.cursor().execute("SELECT 1")
            return True
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Features
    # ------------------------------------------------------------------

    def save_features(
        self,
        location_key: str,
        processing_version: str,
        date_start: str,
        date_end: str,
        features: dict,
        quality: dict,
    ) -> None:
        if self._pool is None:
            return
        now = datetime.now(timezone.utc).isoformat()
        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO location_features
                    (location_key, processing_version, date_start, date_end,
                     features_json, quality_json, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (location_key, processing_version, date_start, date_end)
                DO UPDATE SET
                    features_json = EXCLUDED.features_json,
                    quality_json  = EXCLUDED.quality_json,
                    updated_at    = EXCLUDED.updated_at
                """,
                [location_key, processing_version, date_start, date_end,
                 json.dumps(_round_floats(features)), json.dumps(quality), now],
            )

    def get_features(
        self, location_key: str, processing_version: str, date_start: str, date_end: str
    ) -> dict | None:
        if self._pool is None:
            return None
        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT features_json, quality_json FROM location_features
                WHERE location_key = %s AND processing_version = %s
                  AND date_start = %s AND date_end = %s
                """,
                [location_key, processing_version, date_start, date_end],
            )
            result = cur.fetchone()
        if result is None:
            return None
        return {"features": json.loads(result[0]), "quality": json.loads(result[1])}

    def get_latest_features(self, location_key: str) -> dict | None:
        """Retrieve the most recent features row regardless of date window."""
        if self._pool is None:
            return None
        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT features_json, quality_json, date_start, date_end
                FROM location_features
                WHERE location_key = %s
                ORDER BY updated_at DESC LIMIT 1
                """,
                [location_key],
            )
            result = cur.fetchone()
        if result is None:
            return None
        return {
            "features":   json.loads(result[0]),
            "quality":    json.loads(result[1]),
            "date_start": str(result[2]) if result[2] else None,
            "date_end":   str(result[3]) if result[3] else None,
        }

    # ------------------------------------------------------------------
    # Timeseries
    # ------------------------------------------------------------------

    def save_timeseries(
        self,
        location_key: str,
        processing_version: str,
        cadence: str,
        series: dict,
    ) -> None:
        if self._pool is None:
            return
        now = datetime.now(timezone.utc).isoformat()
        with self._get_conn() as conn:
            cur = conn.cursor()
            for metric, records in series.items():
                def _to_dict(r):
                    if hasattr(r, "model_dump"):
                        return r.model_dump()
                    if dataclasses.is_dataclass(r):
                        return dataclasses.asdict(r)
                    return r
                serialized = json.dumps(_round_floats([_to_dict(r) for r in records]))
                cur.execute(
                    """
                    INSERT INTO location_timeseries
                        (location_key, processing_version, cadence, metric, series_json, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (location_key, processing_version, cadence, metric)
                    DO UPDATE SET
                        series_json = EXCLUDED.series_json,
                        updated_at  = EXCLUDED.updated_at
                    """,
                    [location_key, processing_version, cadence, metric, serialized, now],
                )

    def get_timeseries(
        self,
        location_key: str,
        processing_version: str,
        cadence: str = "monthly",
    ) -> dict[str, list[dict]] | None:
        if self._pool is None:
            return None
        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT metric, series_json FROM location_timeseries
                WHERE location_key = %s AND processing_version = %s AND cadence = %s
                """,
                [location_key, processing_version, cadence],
            )
            rows = cur.fetchall()
            if not rows:
                cur.execute(
                    """
                    SELECT processing_version FROM location_timeseries
                    WHERE location_key = %s AND cadence = %s
                    ORDER BY updated_at DESC LIMIT 1
                    """,
                    [location_key, cadence],
                )
                latest = cur.fetchone()
                if latest:
                    cur.execute(
                        """
                        SELECT metric, series_json FROM location_timeseries
                        WHERE location_key = %s AND processing_version = %s AND cadence = %s
                        """,
                        [location_key, latest[0], cadence],
                    )
                    rows = cur.fetchall()
        if not rows:
            return None
        return {metric: json.loads(series_json) for metric, series_json in rows}

    # ------------------------------------------------------------------
    # Scores
    # ------------------------------------------------------------------

    def save_scores(
        self,
        location_key: str,
        score_version: str,
        lookback_years: int,
        scores: dict,
    ) -> None:
        if self._pool is None:
            return
        now = datetime.now(timezone.utc).isoformat()
        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO location_scores
                    (location_key, score_version, lookback_years, scores_json, updated_at)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (location_key, score_version, lookback_years)
                DO UPDATE SET
                    scores_json = EXCLUDED.scores_json,
                    updated_at  = EXCLUDED.updated_at
                """,
                [location_key, score_version, lookback_years, json.dumps(scores), now],
            )

    def get_scores(self, location_key: str, score_version: str) -> dict | None:
        if self._pool is None:
            return None
        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT scores_json FROM location_scores
                WHERE location_key = %s AND score_version = %s
                ORDER BY updated_at DESC LIMIT 1
                """,
                [location_key, score_version],
            )
            result = cur.fetchone()
            if result is None:
                cur.execute(
                    """
                    SELECT scores_json FROM location_scores
                    WHERE location_key = %s
                    ORDER BY updated_at DESC LIMIT 1
                    """,
                    [location_key],
                )
                result = cur.fetchone()
        if result is None:
            return None
        return json.loads(result[0])

    # ------------------------------------------------------------------
    # Geometry / location management
    # ------------------------------------------------------------------

    def save_geometry(
        self,
        location_key: str,
        geojson: dict,
        name: str | None = None,
        customer_id: str | None = None,
        is_public: bool | None = None,
    ) -> None:
        if self._pool is None:
            return
        now = datetime.now(timezone.utc).isoformat()
        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT name, customer_id, climate_code, is_public FROM location_geometries WHERE location_key = %s",
                [location_key],
            )
            existing = cur.fetchone()
            if existing:
                if name is None:
                    name = existing[0]
                if customer_id is None:
                    customer_id = existing[1]
                existing_code = existing[2]
                if is_public is None:
                    is_public = existing[3]
            else:
                existing_code = None
                if is_public is None:
                    is_public = False

            if customer_id is not None:
                cur.execute(
                    "SELECT 1 FROM users WHERE user_id = %s"
                    " UNION SELECT 1 FROM customers WHERE customer_id = %s",
                    [customer_id, customer_id],
                )
                if not cur.fetchone():
                    customer_id = None

            climate_code = existing_code
            if climate_code is None:
                try:
                    pt = shape(geojson)
                    climate_code = self.lookup_climate(pt.y, pt.x)
                except Exception:
                    pass

            cur.execute(
                """
                INSERT INTO location_geometries
                    (location_key, geojson_text, name, customer_id, climate_code, updated_at, is_public)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (location_key)
                DO UPDATE SET
                    geojson_text = EXCLUDED.geojson_text,
                    name         = EXCLUDED.name,
                    customer_id  = EXCLUDED.customer_id,
                    climate_code = EXCLUDED.climate_code,
                    updated_at   = EXCLUDED.updated_at,
                    is_public    = EXCLUDED.is_public
                """,
                [location_key, json.dumps(geojson), name, customer_id, climate_code, now, is_public],
            )

    def get_geometry(self, location_key: str) -> dict | None:
        if self._pool is None:
            return None
        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT geojson_text FROM location_geometries WHERE location_key = %s",
                [location_key],
            )
            result = cur.fetchone()
        if result is None:
            return None
        return json.loads(result[0])

    def get_location_info(self, location_key: str) -> dict | None:
        if self._pool is None:
            return None
        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT geojson_text, name, climate_code FROM location_geometries WHERE location_key = %s",
                [location_key],
            )
            result = cur.fetchone()
        if result is None:
            return None
        geojson = json.loads(result[0])
        name = result[1]
        climate_code = result[2]
        try:
            centroid = shape(geojson).centroid
            centroid_lonlat = [round(centroid.x, 5), round(centroid.y, 5)]
        except Exception:
            centroid_lonlat = None

        climate_info: dict | None = None
        if climate_code:
            label, criterion = _KG_DESCRIPTIONS.get(climate_code, (None, None))
            main_class = _KG_MAIN.get(climate_code[0]) if climate_code else None
            climate_info = {
                "code":       climate_code,
                "label":      label or climate_code,
                "criterion":  criterion,
                "main_class": main_class,
            }

        return {"geojson": geojson, "name": name, "centroid": centroid_lonlat, "climate": climate_info}

    def _locations_query(self, where: str = "", params: list = []) -> list[dict]:
        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                f"""
                WITH latest_features AS (
                    SELECT location_key, processing_version, features_json
                    FROM (
                        SELECT location_key, processing_version, features_json,
                               ROW_NUMBER() OVER (PARTITION BY location_key ORDER BY updated_at DESC) AS rn
                        FROM location_features
                    ) sub WHERE rn = 1
                ),
                latest_scores AS (
                    SELECT location_key, score_version, scores_json
                    FROM (
                        SELECT location_key, score_version, scores_json,
                               ROW_NUMBER() OVER (PARTITION BY location_key ORDER BY updated_at DESC) AS rn
                        FROM location_scores
                    ) sub WHERE rn = 1
                )
                SELECT pg.location_key, pg.geojson_text, pg.name, pg.customer_id,
                       c.name AS customer_name, pg.updated_at,
                       lf.processing_version, ls.score_version,
                       lf.features_json, ls.scores_json, pg.is_public
                FROM location_geometries pg
                LEFT JOIN customers c ON pg.customer_id = c.customer_id
                LEFT JOIN latest_features lf ON lf.location_key = pg.location_key
                LEFT JOIN latest_scores ls ON ls.location_key = pg.location_key
                {where}
                ORDER BY pg.updated_at DESC
                """,
                params,
            )
            rows = cur.fetchall()

        result = []
        for (location_key, geojson_text, name, customer_id, customer_name,
             updated_at, processing_version, score_version,
             features_json_str, scores_json_str, is_public) in rows:
            try:
                geojson = json.loads(geojson_text)
                centroid = shape(geojson).centroid
                centroid_lonlat = [round(centroid.x, 5), round(centroid.y, 5)]
            except Exception:
                centroid_lonlat = None
            quality_score: float | None = None
            composite_score: int | None = None
            active_episodes: list[str] = []
            if features_json_str:
                try:
                    _feat = json.loads(features_json_str)
                    quality_score = _feat.get("quality_score")
                    for _ep in ("active_flood", "active_fire", "active_drought"):
                        if (_feat.get(_ep) or 0.0) > 0.5:
                            active_episodes.append(_ep)
                except Exception:
                    pass
            if scores_json_str:
                try:
                    composite_score = json.loads(scores_json_str).get("composite_score")
                except Exception:
                    pass
            result.append({
                "location_key":    location_key,
                "name":            name,
                "customer_id":     customer_id,
                "customer_name":   customer_name,
                "centroid":        centroid_lonlat,
                "updated_at":      updated_at.isoformat() if hasattr(updated_at, "isoformat") else str(updated_at),
                "processing_version": processing_version,
                "score_version":   score_version,
                "quality_score":   quality_score,
                "composite_score": composite_score,
                "active_episodes": active_episodes,
                "is_public":       bool(is_public),
                "report_url":      f"/v1/location/{location_key}/report",
                "thumbnail_url":   f"/v1/thumbnail/{location_key}.png",
            })
        return result

    def get_all_locations(self) -> list[dict]:
        if self._pool is None:
            return []
        return self._locations_query()

    def get_public_locations(self) -> list[dict]:
        if self._pool is None:
            return []
        return self._locations_query("WHERE pg.is_public = TRUE")

    def get_customer_locations(self, customer_id: str) -> list[dict]:
        if self._pool is None:
            return []
        return self._locations_query("WHERE pg.customer_id = %s", [customer_id])

    def delete_location(self, location_key: str) -> dict[str, int]:
        if self._pool is None:
            return {}
        tables = [
            "scene_bands",
            "sar_scene_bands",
            "location_timeseries",
            "location_scores",
            "location_features",
            "location_geometries",
        ]
        deleted: dict[str, int] = {}
        with self._get_conn() as conn:
            cur = conn.cursor()
            for table in tables:
                cur.execute(
                    f"DELETE FROM {table} WHERE location_key = %s RETURNING 1",
                    [location_key],
                )
                deleted[table] = len(cur.fetchall())
        return deleted

    # ------------------------------------------------------------------
    # Customers
    # ------------------------------------------------------------------

    def create_customer(self, name: str) -> dict:
        if self._pool is None:
            raise RuntimeError("DB not connected")
        now = datetime.now(timezone.utc).isoformat()
        with self._get_conn() as conn:
            cur = conn.cursor()
            for _ in range(5):
                customer_id = secrets.token_hex(3)
                cur.execute(
                    "SELECT customer_id FROM customers WHERE customer_id = %s", [customer_id]
                )
                if cur.fetchone() is None:
                    break
            cur.execute(
                "INSERT INTO customers (customer_id, name, created_at) VALUES (%s, %s, %s)",
                [customer_id, name, now],
            )
        return {"customer_id": customer_id, "name": name, "created_at": now}

    def get_customer(self, customer_id: str) -> dict | None:
        if self._pool is None:
            return None
        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT customer_id, name, created_at FROM customers WHERE customer_id = %s",
                [customer_id],
            )
            row = cur.fetchone()
        if row is None:
            return None
        return {
            "customer_id": row[0],
            "name":        row[1],
            "created_at":  row[2].isoformat() if hasattr(row[2], "isoformat") else str(row[2]),
        }

    def get_all_customers(self) -> list[dict]:
        if self._pool is None:
            return []
        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT customer_id, name, created_at FROM customers ORDER BY name")
            rows = cur.fetchall()
        return [
            {
                "customer_id": row[0],
                "name":        row[1],
                "created_at":  row[2].isoformat() if hasattr(row[2], "isoformat") else str(row[2]),
            }
            for row in rows
        ]

    # ------------------------------------------------------------------
    # Users
    # ------------------------------------------------------------------

    def create_user(self, email: str, password_hash: str, name: str | None = None) -> dict:
        if self._pool is None:
            raise RuntimeError("DB not connected")
        with self._get_conn() as conn:
            cur = conn.cursor()
            for _ in range(5):
                user_id = secrets.token_hex(3)
                cur.execute("SELECT 1 FROM users WHERE user_id = %s", [user_id])
                if cur.fetchone() is None:
                    break
            cur.execute(
                "INSERT INTO users (user_id, email, password_hash, name) VALUES (%s, %s, %s, %s)",
                [user_id, email, password_hash, name],
            )
        return {"user_id": user_id, "email": email, "name": name, "role": "user"}

    def get_user_by_email(self, email: str) -> dict | None:
        if self._pool is None:
            return None
        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT user_id, email, password_hash, name, role, is_verified, created_at"
                " FROM users WHERE email = %s",
                [email],
            )
            row = cur.fetchone()
        if row is None:
            return None
        return {
            "user_id": row[0], "email": row[1], "password_hash": row[2],
            "name": row[3], "role": row[4], "is_verified": row[5],
            "created_at": row[6].isoformat() if hasattr(row[6], "isoformat") else str(row[6]),
        }

    def get_user_by_id(self, user_id: str) -> dict | None:
        if self._pool is None:
            return None
        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT user_id, email, name, role, is_verified, created_at"
                " FROM users WHERE user_id = %s",
                [user_id],
            )
            row = cur.fetchone()
        if row is None:
            return None
        return {
            "user_id": row[0], "email": row[1], "name": row[2],
            "role": row[3], "is_verified": row[4],
            "created_at": row[5].isoformat() if hasattr(row[5], "isoformat") else str(row[5]),
        }

    def create_verification_token(self, user_id: str) -> str:
        if self._pool is None:
            raise RuntimeError("DB not connected")
        token = str(uuid.uuid4())
        expires_at = datetime.now(timezone.utc) + timedelta(hours=24)
        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO email_verification_tokens (token, user_id, expires_at)"
                " VALUES (%s, %s, %s)",
                [token, user_id, expires_at],
            )
        return token

    def consume_verification_token(self, token: str) -> str | None:
        """Return user_id if the token is valid, unused, and unexpired; else None."""
        if self._pool is None:
            return None
        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT user_id, expires_at, used_at FROM email_verification_tokens WHERE token = %s",
                [token],
            )
            row = cur.fetchone()
            if row is None:
                return None
            user_id, expires_at, used_at = row
            if used_at is not None:
                return None
            exp = expires_at if expires_at.tzinfo else expires_at.replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) > exp:
                return None
            cur.execute(
                "UPDATE email_verification_tokens SET used_at = %s WHERE token = %s",
                [datetime.now(timezone.utc), token],
            )
        return user_id

    def mark_user_verified(self, user_id: str) -> None:
        if self._pool is None:
            return
        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute("UPDATE users SET is_verified = TRUE WHERE user_id = %s", [user_id])

    def location_owned_by(self, location_key: str, user_id: str) -> bool:
        if self._pool is None:
            return False
        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT 1 FROM location_geometries WHERE location_key = %s AND customer_id = %s",
                [location_key, user_id],
            )
            return cur.fetchone() is not None

    # ------------------------------------------------------------------
    # Scene band cache (S2 optical)
    # ------------------------------------------------------------------

    def store_scene_bands(
        self,
        location_key: str,
        scene_id: str,
        month_key: str,
        processing_version: str,
        bands: dict[str, np.ndarray],
        cloud_fraction: float = 0.0,
    ) -> None:
        if self._pool is None:
            return
        now = datetime.now(timezone.utc).isoformat()
        with self._get_conn() as conn:
            cur = conn.cursor()
            for band_key, arr in bands.items():
                h, w = arr.shape
                data = arr.astype(np.float32).tobytes()
                cur.execute(
                    """
                    INSERT INTO scene_bands
                        (location_key, scene_id, month_key, processing_version,
                         band_key, width, height, data, cloud_fraction, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (location_key, scene_id, processing_version, band_key)
                    DO UPDATE SET
                        data           = EXCLUDED.data,
                        cloud_fraction = EXCLUDED.cloud_fraction
                    """,
                    [location_key, scene_id, month_key, processing_version,
                     band_key, w, h, psycopg2.Binary(data), cloud_fraction, now],
                )

    def load_scene_bands(
        self,
        location_key: str,
        scene_id: str,
        processing_version: str,
        band_keys: list[str],
    ) -> dict[str, np.ndarray] | None:
        if self._pool is None:
            return None
        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT band_key, width, height, data FROM scene_bands
                WHERE location_key = %s AND scene_id = %s AND processing_version = %s
                  AND band_key = ANY(%s)
                """,
                [location_key, scene_id, processing_version, band_keys],
            )
            rows = cur.fetchall()
        if len(rows) < len(band_keys):
            return None
        result: dict[str, np.ndarray] = {}
        for band_key, w, h, data in rows:
            result[band_key] = _frombuffer(data).reshape(h, w)
        if not all(k in result for k in band_keys):
            return None
        return result

    def delete_scene_bands(
        self,
        location_key: str,
        scene_id: str,
        processing_version: str,
    ) -> None:
        if self._pool is None:
            return
        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                DELETE FROM scene_bands
                WHERE location_key = %s AND scene_id = %s AND processing_version = %s
                """,
                [location_key, scene_id, processing_version],
            )

    def get_scene_months(
        self,
        location_key: str,
        processing_version: str,
        limit: int = 12,
    ) -> list[dict]:
        if self._pool is None:
            return []
        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT 1 FROM scene_bands WHERE location_key = %s AND processing_version = %s LIMIT 1",
                [location_key, processing_version],
            )
            if cur.fetchone() is None:
                cur.execute(
                    "SELECT processing_version FROM scene_bands WHERE location_key = %s ORDER BY created_at DESC LIMIT 1",
                    [location_key],
                )
                latest = cur.fetchone()
                if latest:
                    processing_version = latest[0]

            max_cloud = 1.0 - settings.MIN_VALID_PIXEL_FRACTION
            cur.execute(
                """
                SELECT scene_id, month_key FROM (
                    SELECT scene_id, month_key, MIN(cloud_fraction) AS cf,
                           ROW_NUMBER() OVER (PARTITION BY month_key ORDER BY MIN(cloud_fraction) ASC) AS rn
                    FROM scene_bands
                    WHERE location_key = %s AND processing_version = %s
                    GROUP BY scene_id, month_key
                    HAVING MIN(cloud_fraction) <= %s
                ) sub
                WHERE rn = 1
                ORDER BY month_key DESC
                LIMIT %s
                """,
                [location_key, processing_version, max_cloud, limit],
            )
            scenes = cur.fetchall()

            result = []
            for scene_id, month_key in scenes:
                cur.execute(
                    """
                    SELECT band_key, width, height, data FROM scene_bands
                    WHERE location_key = %s AND scene_id = %s AND processing_version = %s
                    """,
                    [location_key, scene_id, processing_version],
                )
                rows = cur.fetchall()
                bands = {
                    band_key: _frombuffer(data).reshape(h, w)
                    for band_key, w, h, data in rows
                }
                result.append({"scene_id": scene_id, "month_key": month_key, "bands": bands})
        return result

    # ------------------------------------------------------------------
    # SAR scene cache
    # ------------------------------------------------------------------

    def store_sar_scene(
        self,
        location_key: str,
        scene_id: str,
        month_key: str,
        processing_version: str,
        vv_dn: np.ndarray,
        water_frac: float,
        rel_orbit: int = 0,
    ) -> None:
        if self._pool is None:
            return
        h, w = vv_dn.shape
        data = vv_dn.astype(np.float32).tobytes()
        now = datetime.now(timezone.utc).isoformat()
        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO sar_scene_bands
                    (location_key, scene_id, month_key, processing_version,
                     width, height, vv_data, water_frac, rel_orbit, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (location_key, scene_id, processing_version)
                DO UPDATE SET
                    vv_data    = EXCLUDED.vv_data,
                    water_frac = EXCLUDED.water_frac,
                    rel_orbit  = EXCLUDED.rel_orbit
                """,
                [location_key, scene_id, month_key, processing_version,
                 w, h, psycopg2.Binary(data), round(water_frac, 4), rel_orbit, now],
            )

    def get_sar_scene_months(
        self,
        location_key: str,
        processing_version: str,
        limit: int = 12,
    ) -> list[dict]:
        if self._pool is None:
            return []
        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT 1 FROM sar_scene_bands WHERE location_key = %s AND processing_version = %s LIMIT 1",
                [location_key, processing_version],
            )
            if cur.fetchone() is None:
                cur.execute(
                    "SELECT processing_version FROM sar_scene_bands WHERE location_key = %s ORDER BY created_at DESC LIMIT 1",
                    [location_key],
                )
                latest = cur.fetchone()
                if latest:
                    processing_version = latest[0]

            cur.execute(
                """
                WITH recent_months AS (
                    SELECT DISTINCT month_key
                    FROM sar_scene_bands
                    WHERE location_key = %s AND processing_version = %s
                    ORDER BY month_key DESC
                    LIMIT %s
                )
                SELECT s.scene_id, s.month_key, s.width, s.height, s.vv_data,
                       s.water_frac, COALESCE(s.rel_orbit, 0)
                FROM sar_scene_bands s
                JOIN recent_months rm ON s.month_key = rm.month_key
                WHERE s.location_key = %s AND s.processing_version = %s
                ORDER BY s.month_key DESC, COALESCE(s.rel_orbit, 0) ASC
                """,
                [location_key, processing_version, limit, location_key, processing_version],
            )
            scenes = cur.fetchall()

        result = []
        for scene_id, month_key, w, h, vv_data, water_frac, rel_orbit in scenes:
            vv_dn = _frombuffer(vv_data).reshape(h, w).astype(np.uint16)
            result.append({
                "scene_id":   scene_id,
                "month_key":  month_key,
                "rel_orbit":  int(rel_orbit),
                "vv_dn":      vv_dn,
                "water_frac": water_frac,
            })
        return result

    def get_sar_scene_fracs(
        self,
        location_key: str,
        processing_version: str,
    ) -> list[tuple[str, float]]:
        if self._pool is None:
            return []
        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT month_key, water_frac
                FROM sar_scene_bands
                WHERE location_key = %s AND processing_version = %s
                ORDER BY month_key ASC
                """,
                [location_key, processing_version],
            )
            rows = cur.fetchall()
        return [(row[0], row[1]) for row in rows if row[1] is not None]

    def get_sar_scene_fracs_with_orbit(
        self,
        location_key: str,
        processing_version: str,
    ) -> list[tuple[str, float, int]]:
        if self._pool is None:
            return []
        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT month_key, water_frac, COALESCE(rel_orbit, 0)
                FROM sar_scene_bands
                WHERE location_key = %s AND processing_version = %s
                ORDER BY month_key ASC
                """,
                [location_key, processing_version],
            )
            rows = cur.fetchall()
            if not rows:
                cur.execute(
                    "SELECT processing_version FROM sar_scene_bands WHERE location_key = %s ORDER BY created_at DESC LIMIT 1",
                    [location_key],
                )
                latest = cur.fetchone()
                if latest:
                    cur.execute(
                        """
                        SELECT month_key, water_frac, COALESCE(rel_orbit, 0)
                        FROM sar_scene_bands
                        WHERE location_key = %s AND processing_version = %s
                        ORDER BY month_key ASC
                        """,
                        [location_key, latest[0]],
                    )
                    rows = cur.fetchall()
        return [(row[0], float(row[1]), int(row[2])) for row in rows if row[1] is not None]

    def delete_sar_scenes(self, location_key: str, processing_version: str) -> int:
        if self._pool is None:
            return 0
        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                "DELETE FROM sar_scene_bands WHERE location_key = %s AND processing_version = %s RETURNING 1",
                [location_key, processing_version],
            )
            return len(cur.fetchall())

    # ------------------------------------------------------------------
    # TerraClimate monthly cache
    # ------------------------------------------------------------------

    def get_terraclimate_monthly(
        self,
        grid_lat: float,
        grid_lon: float,
        variables: list[str],
        years: list[int],
    ) -> dict[str, dict[tuple[int, int], float | None]]:
        if self._pool is None or not variables or not years:
            return {var: {} for var in variables}
        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT variable, year, month, value
                FROM terraclimate_monthly
                WHERE grid_lat = %s AND grid_lon = %s
                  AND variable = ANY(%s)
                  AND year = ANY(%s)
                """,
                [grid_lat, grid_lon, variables, years],
            )
            rows = cur.fetchall()
        result: dict[str, dict[tuple[int, int], float | None]] = {var: {} for var in variables}
        for variable, year, month, value in rows:
            if variable in result:
                result[variable][(int(year), int(month))] = value
        return result

    def store_terraclimate_monthly(
        self,
        grid_lat: float,
        grid_lon: float,
        rows: list[dict],
    ) -> None:
        if self._pool is None or not rows:
            return
        with self._get_conn() as conn:
            cur = conn.cursor()
            for row in rows:
                cur.execute(
                    """
                    INSERT INTO terraclimate_monthly
                        (grid_lat, grid_lon, variable, year, month, value)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (grid_lat, grid_lon, variable, year, month)
                    DO UPDATE SET value = EXCLUDED.value
                    """,
                    [grid_lat, grid_lon, row["variable"], row["year"], row["month"],
                     round(row["value"], 4) if row["value"] is not None else None],
                )

    def get_all_terraclimate_for_grid(
        self,
        grid_lat: float,
        grid_lon: float,
    ) -> dict[str, list[tuple[int, int, float | None]]]:
        if self._pool is None:
            return {}
        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT variable, year, month, value
                FROM terraclimate_monthly
                WHERE grid_lat = %s AND grid_lon = %s
                ORDER BY variable, year, month
                """,
                [grid_lat, grid_lon],
            )
            rows = cur.fetchall()
        result: dict[str, list[tuple[int, int, float | None]]] = {}
        for variable, year, month, value in rows:
            result.setdefault(variable, []).append((int(year), int(month), value))
        return result

    # ------------------------------------------------------------------
    # NOAA tidal stations cache
    # ------------------------------------------------------------------

    def store_tidal_stations(self, stations: list[dict]) -> None:
        if self._pool is None:
            return
        fetched_at = datetime.now(timezone.utc).isoformat()
        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute("DELETE FROM noaa_tidal_stations")
            psycopg2.extras.execute_values(
                cur,
                """
                INSERT INTO noaa_tidal_stations
                    (station_id, name, lat, lon, state, tide_type, fetched_at)
                VALUES %s
                """,
                [
                    (s["station_id"], s["name"], s["lat"], s["lon"],
                     s.get("state", ""), s.get("tide_type", ""), fetched_at)
                    for s in stations
                ],
            )

    def needs_tidal_station_refresh(self, max_age_days: int) -> bool:
        if self._pool is None:
            return False
        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT MIN(fetched_at) FROM noaa_tidal_stations")
            row = cur.fetchone()
        if row is None or row[0] is None:
            return True
        oldest_str = row[0]
        try:
            oldest = datetime.fromisoformat(oldest_str)
            if oldest.tzinfo is None:
                oldest = oldest.replace(tzinfo=timezone.utc)
            age_days = (datetime.now(timezone.utc) - oldest).days
            return age_days >= max_age_days
        except Exception:
            return True

    def get_nearest_tidal_station(
        self, lat: float, lon: float, max_distance_km: float
    ) -> dict | None:
        if self._pool is None:
            return None
        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT station_id, name, lat, lon, tide_type, state,
                    6371.0 * 2 * asin(sqrt(
                        power(sin(radians((lat - %s) / 2)), 2) +
                        cos(radians(%s)) * cos(radians(lat)) *
                        power(sin(radians((lon - %s) / 2)), 2)
                    )) AS distance_km
                FROM noaa_tidal_stations
                ORDER BY distance_km ASC
                LIMIT 1
                """,
                [lat, lat, lon],
            )
            result = cur.fetchone()
        if result is None:
            return None
        station_id, name, slat, slon, tide_type, state, distance_km = result
        if distance_km > max_distance_km:
            return None
        return {
            "station_id":  station_id,
            "name":        name,
            "lat":         slat,
            "lon":         slon,
            "tide_type":   tide_type,
            "state":       state,
            "distance_km": round(distance_km, 2),
        }

    # ------------------------------------------------------------------
    # NOAA tidal predictions cache
    # ------------------------------------------------------------------

    def get_cached_tide_dates(self, station_id: str, date_strs: list[str]) -> set[str]:
        if self._pool is None or not date_strs:
            return set()
        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT DISTINCT date FROM noaa_tide_predictions WHERE station_id = %s AND date = ANY(%s)",
                [station_id, date_strs],
            )
            rows = cur.fetchall()
        return {row[0] for row in rows}

    def store_tide_predictions(
        self, station_id: str, date_str: str, rows: list[tuple[int, float]]
    ) -> None:
        if self._pool is None or not rows:
            return
        with self._get_conn() as conn:
            cur = conn.cursor()
            psycopg2.extras.execute_values(
                cur,
                """
                INSERT INTO noaa_tide_predictions (station_id, date, hour, water_level_m)
                VALUES %s
                ON CONFLICT (station_id, date, hour)
                DO UPDATE SET water_level_m = EXCLUDED.water_level_m
                """,
                [(station_id, date_str, hour, round(level, 4)) for hour, level in rows],
            )

    def get_tide_predictions(
        self, station_id: str, date_strs: list[str]
    ) -> dict[str, list[tuple[int, float]]]:
        if self._pool is None or not date_strs:
            return {}
        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT date, hour, water_level_m FROM noaa_tide_predictions
                WHERE station_id = %s AND date = ANY(%s)
                ORDER BY date, hour
                """,
                [station_id, date_strs],
            )
            rows = cur.fetchall()
        result: dict[str, list[tuple[int, float]]] = {}
        for date_str, hour, level in rows:
            if level is not None:
                result.setdefault(date_str, []).append((int(hour), float(level)))
        return result

    # ------------------------------------------------------------------
    # Copernicus GLO-30 elevation cache
    # ------------------------------------------------------------------

    def get_elevation(self, location_key: str) -> dict[str, float] | None:
        if self._pool is None:
            return None
        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT elevation_m, elevation_range_m, slope_deg, elevation_min_m, elevation_max_m,
                       aspect_deg, tpi_m, curvature, heat_load_index
                FROM elevation_cache WHERE location_key = %s
                """,
                [location_key],
            )
            row = cur.fetchone()
        if row is None:
            return None
        return {
            "elevation_m":       row[0],
            "elevation_range_m": row[1],
            "slope_deg":         row[2],
            "elevation_min_m":   row[3],
            "elevation_max_m":   row[4],
            "aspect_deg":        row[5],
            "tpi_m":             row[6],
            "curvature":         row[7],
            "heat_load_index":   row[8],
        }

    def get_elevation_array(self, location_key: str) -> bytes | None:
        if self._pool is None:
            return None
        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT elevation_array FROM elevation_cache WHERE location_key = %s",
                [location_key],
            )
            row = cur.fetchone()
        if row is None or row[0] is None:
            return None
        val = row[0]
        return bytes(val) if isinstance(val, memoryview) else val

    def store_elevation(self, location_key: str, data: dict) -> None:
        if self._pool is None:
            return
        elev_arr = data.get("elevation_array")
        if isinstance(elev_arr, (bytes, bytearray, memoryview)):
            elev_arr = psycopg2.Binary(bytes(elev_arr))
        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO elevation_cache
                    (location_key, elevation_m, elevation_range_m, slope_deg,
                     elevation_min_m, elevation_max_m,
                     aspect_deg, tpi_m, curvature, heat_load_index, elevation_array)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (location_key)
                DO UPDATE SET
                    elevation_m       = EXCLUDED.elevation_m,
                    elevation_range_m = EXCLUDED.elevation_range_m,
                    slope_deg         = EXCLUDED.slope_deg,
                    elevation_min_m   = EXCLUDED.elevation_min_m,
                    elevation_max_m   = EXCLUDED.elevation_max_m,
                    aspect_deg        = EXCLUDED.aspect_deg,
                    tpi_m             = EXCLUDED.tpi_m,
                    curvature         = EXCLUDED.curvature,
                    heat_load_index   = EXCLUDED.heat_load_index,
                    elevation_array   = EXCLUDED.elevation_array
                """,
                [
                    location_key,
                    data.get("elevation_m"),
                    data.get("elevation_range_m"),
                    data.get("slope_deg"),
                    data.get("elevation_min_m"),
                    data.get("elevation_max_m"),
                    data.get("aspect_deg"),
                    data.get("tpi_m"),
                    data.get("curvature"),
                    data.get("heat_load_index"),
                    elev_arr,
                ],
            )


store = PostgresStore()
# Backward-compat alias used by pipeline/timeseries.py: `from ..storage.duckdb_store import store as duckdb_store`
duckdb_store = store
