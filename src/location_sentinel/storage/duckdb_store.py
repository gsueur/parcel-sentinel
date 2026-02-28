from __future__ import annotations

import dataclasses
import json
import logging
import math
import os
import secrets
from datetime import datetime, timezone

import duckdb
import numpy as np
from shapely.geometry import shape

from ..config import settings

# ---------------------------------------------------------------------------
# Koeppen-Geiger climate classification metadata
# ---------------------------------------------------------------------------
_KG_DESCRIPTIONS: dict[str, tuple[str, str]] = {
    # code: (standard climate name, quantitative criterion)
    # -- Tropical --
    "Af": ("Tropical rainforest climate",                                           "Pmin ≥ 60 mm/month"),
    "Am": ("Tropical monsoon climate",                                              "Pann ≥ 25(100−Pmin)"),
    "As": ("Tropical dry savanna climate",                                          "Pmin < 60 mm in summer"),
    "Aw": ("Tropical savanna climate (wet)",                                        "Pmin < 60 mm in winter"),
    # -- Arid --
    "BWh": ("Hot desert climate",                                                   "Pann ≤ 5 Pth, Tann ≥ +18 °C"),
    "BWk": ("Cold desert climate",                                                  "Pann ≤ 5 Pth, Tann < +18 °C"),
    "BSh": ("Hot semi-arid (steppe) climate",                                       "5 Pth < Pann ≤ 10 Pth, Tann ≥ +18 °C"),
    "BSk": ("Cold semi-arid (steppe) climate",                                      "5 Pth < Pann ≤ 10 Pth, Tann < +18 °C"),
    # -- Temperate --
    "Cfa": ("Humid subtropical climate",                                            "No dry season, Thot ≥ +22 °C"),
    "Cfb": ("Temperate oceanic climate",                                            "No dry season, 4+ months ≥ +10 °C, Thot < +22 °C"),
    "Cfc": ("Subpolar oceanic climate",                                             "No dry season, 1–3 months ≥ +10 °C"),
    "Csa": ("Hot-summer Mediterranean climate",                                     "Dry summer, Thot ≥ +22 °C"),
    "Csb": ("Warm-summer Mediterranean climate",                                    "Dry summer, Thot < +22 °C, 4+ months ≥ +10 °C"),
    "Csc": ("Cool-summer Mediterranean climate",                                    "Dry summer, 1–3 months ≥ +10 °C"),
    "Cwa": ("Monsoon-influenced humid subtropical climate",                         "Dry winter, Thot ≥ +22 °C"),
    "Cwb": ("Subtropical highland / oceanic climate with dry winters",              "Dry winter, Thot < +22 °C, 4+ months ≥ +10 °C"),
    "Cwc": ("Cold subtropical highland / subpolar oceanic climate with dry winters","Dry winter, 1–3 months ≥ +10 °C"),
    # -- Continental --
    "Dfa": ("Hot-summer humid continental climate",                                 "No dry season, Thot ≥ +22 °C"),
    "Dfb": ("Warm-summer humid continental climate",                                "No dry season, Thot < +22 °C, 4+ months ≥ +10 °C"),
    "Dfc": ("Subarctic climate",                                                    "No dry season, 1–3 months ≥ +10 °C"),
    "Dfd": ("Extremely cold subarctic climate",                                     "No dry season, Tcold ≤ −38 °C"),
    "Dsa": ("Hot, dry-summer continental climate",                                  "Dry summer, Thot ≥ +22 °C"),
    "Dsb": ("Warm, dry-summer continental climate",                                 "Dry summer, Thot < +22 °C, 4+ months ≥ +10 °C"),
    "Dsc": ("Dry-summer subarctic climate",                                         "Dry summer, 1–3 months ≥ +10 °C"),
    "Dsd": ("Dry-summer extremely cold subarctic climate",                          "Dry summer, Tcold ≤ −38 °C"),
    "Dwa": ("Monsoon-influenced hot-summer humid continental climate",              "Dry winter, Thot ≥ +22 °C"),
    "Dwb": ("Monsoon-influenced warm-summer humid continental climate",             "Dry winter, Thot < +22 °C, 4+ months ≥ +10 °C"),
    "Dwc": ("Monsoon-influenced subarctic climate",                                 "Dry winter, 1–3 months ≥ +10 °C"),
    "Dwd": ("Monsoon-influenced extremely cold subarctic climate",                  "Dry winter, Tcold ≤ −38 °C"),
    # -- Polar --
    "ET":  ("Tundra climate",                                                       "0 °C ≤ Thot < +10 °C"),
    "EF":  ("Ice cap climate",                                                      "Thot < 0 °C"),
}

# Main-class descriptions (first letter)
_KG_MAIN: dict[str, str] = {
    "A": "Tropical",
    "B": "Arid",
    "C": "Temperate",
    "D": "Cold (continental)",
    "E": "Polar",
}


def _snap_to_koeppen_grid(coord: float) -> float:
    """Snap a lat or lon to the nearest 0.5° Koeppen-Geiger grid center.

    Grid centers are at values of the form n × 0.5 + 0.25 (e.g. -89.75, -89.25, …).
    """
    return math.floor(coord / 0.5) * 0.5 + 0.25

logger = logging.getLogger(__name__)


class DuckDBStore:
    """DuckDB persistence layer for location features, timeseries, and scores."""

    def __init__(self, db_path: str = settings.DUCKDB_PATH):
        self._db_path = db_path
        self._conn: duckdb.DuckDBPyConnection | None = None

    def connect(self) -> None:
        self._conn = duckdb.connect(self._db_path)
        self._create_tables()

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    def _create_tables(self) -> None:
        assert self._conn is not None
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS location_features (
                location_key VARCHAR,
                processing_version VARCHAR,
                date_start VARCHAR,
                date_end VARCHAR,
                features_json VARCHAR,
                quality_json VARCHAR,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (location_key, processing_version, date_start, date_end)
            )
        """)
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS location_timeseries (
                location_key VARCHAR,
                processing_version VARCHAR,
                cadence VARCHAR,
                metric VARCHAR,
                series_json VARCHAR,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (location_key, processing_version, cadence, metric)
            )
        """)
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS location_scores (
                location_key VARCHAR,
                score_version VARCHAR,
                lookback_years INTEGER,
                scores_json VARCHAR,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (location_key, score_version, lookback_years)
            )
        """)
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS customers (
                customer_id VARCHAR PRIMARY KEY,
                name VARCHAR NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS location_geometries (
                location_key VARCHAR PRIMARY KEY,
                geojson_text VARCHAR,
                name VARCHAR,
                customer_id VARCHAR REFERENCES customers(customer_id),
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # Migrations for existing databases
        # Rename tables from old "parcel_*" naming to "location_*"
        for old, new in [
            ("parcel_features", "location_features"),
            ("parcel_timeseries", "location_timeseries"),
            ("parcel_scores", "location_scores"),
            ("parcel_geometries", "location_geometries"),
        ]:
            try:
                self._conn.execute(f"ALTER TABLE {old} RENAME TO {new}")
            except Exception:
                pass
        # Rename parcel_key column in each table
        for table in ["location_features", "location_timeseries", "location_scores",
                      "location_geometries"]:
            try:
                self._conn.execute(f"ALTER TABLE {table} RENAME COLUMN parcel_key TO location_key")
            except Exception:
                pass
        # Rename parcel_key in scene_bands (created separately below)
        # Column additions for existing databases
        for col_def in [
            "ALTER TABLE location_geometries ADD COLUMN IF NOT EXISTS name VARCHAR",
            "ALTER TABLE location_geometries ADD COLUMN IF NOT EXISTS customer_id VARCHAR",
        ]:
            try:
                self._conn.execute(col_def)
            except Exception:
                pass
        # Rename parcel_key → location_key in scene_bands if it exists with old column name
        try:
            self._conn.execute("ALTER TABLE scene_bands RENAME COLUMN parcel_key TO location_key")
        except Exception:
            pass
        # climate_code on location_geometries
        try:
            self._conn.execute(
                "ALTER TABLE location_geometries ADD COLUMN IF NOT EXISTS climate_code VARCHAR"
            )
        except Exception:
            pass
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS scene_bands (
                location_key VARCHAR NOT NULL,
                scene_id VARCHAR NOT NULL,
                month_key VARCHAR NOT NULL,
                processing_version VARCHAR NOT NULL,
                band_key VARCHAR NOT NULL,
                width UTINYINT NOT NULL DEFAULT 64,
                height UTINYINT NOT NULL DEFAULT 64,
                data FLOAT[4096] NOT NULL,
                cloud_fraction DOUBLE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (location_key, scene_id, processing_version, band_key)
            )
        """)

        # Migrate: drop old sar_scene_bands if it was created with USMALLINT column
        # (float32 storage is required to match the scene_bands pattern)
        try:
            col = self._conn.execute(
                "SELECT data_type FROM information_schema.columns "
                "WHERE table_name='sar_scene_bands' AND column_name='vv_data'"
            ).fetchone()
            if col and "SMALLINT" in col[0].upper():
                self._conn.execute("DROP TABLE sar_scene_bands")
        except Exception:
            pass

        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS sar_scene_bands (
                location_key VARCHAR NOT NULL,
                scene_id VARCHAR NOT NULL,
                month_key VARCHAR NOT NULL,
                processing_version VARCHAR NOT NULL,
                width UTINYINT NOT NULL DEFAULT 64,
                height UTINYINT NOT NULL DEFAULT 64,
                vv_data FLOAT[4096] NOT NULL,
                water_frac DOUBLE,
                rel_orbit SMALLINT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (location_key, scene_id, processing_version)
            )
        """)
        # Migration: add rel_orbit column to existing databases and backfill from scene_id.
        # Scene ID format: S1[AB]_IW_GRDH_1SDV_..._AAAAAA_TTTTTT
        # rel_orbit (S1A) = (abs_orbit - 73) % 175 + 1
        # rel_orbit (S1B) = (abs_orbit - 26) % 175 + 1
        try:
            self._conn.execute(
                "ALTER TABLE sar_scene_bands ADD COLUMN IF NOT EXISTS rel_orbit SMALLINT"
            )
        except Exception:
            pass
        try:
            self._conn.execute("""
                UPDATE sar_scene_bands SET rel_orbit = (
                    CASE
                        WHEN scene_id LIKE 'S1B%'
                        THEN ((CAST(split_part(scene_id, '_', 7) AS INTEGER) - 26) % 175) + 1
                        ELSE ((CAST(split_part(scene_id, '_', 7) AS INTEGER) - 73) % 175) + 1
                    END
                ) WHERE rel_orbit IS NULL
            """)
            self._conn.commit()
        except Exception:
            pass

        # TerraClimate monthly cache (grid-cell keyed, shared across locations)
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS terraclimate_monthly (
                grid_lat FLOAT NOT NULL,
                grid_lon FLOAT NOT NULL,
                variable VARCHAR NOT NULL,
                year INTEGER NOT NULL,
                month INTEGER NOT NULL,
                value FLOAT,
                PRIMARY KEY (grid_lat, grid_lon, variable, year, month)
            )
        """)

        # Climate reference tables
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS climate_descriptions (
                code    VARCHAR PRIMARY KEY,
                label   VARCHAR NOT NULL,
                criterion VARCHAR
            )
        """)
        # Populate reference table (INSERT OR IGNORE keeps it idempotent)
        for code, (label, criterion) in _KG_DESCRIPTIONS.items():
            self._conn.execute(
                "INSERT OR IGNORE INTO climate_descriptions (code, label, criterion) VALUES (?, ?, ?)",
                [code, label, criterion],
            )
        # Raw KG grid table
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS climates (
                lat DOUBLE NOT NULL,
                lon DOUBLE NOT NULL,
                code VARCHAR NOT NULL,
                PRIMARY KEY (lat, lon)
            )
        """)
        # Load file only if table is empty
        count = self._conn.execute("SELECT COUNT(*) FROM climates").fetchone()[0]
        if count == 0:
            self._load_koeppen_file()

    def _load_koeppen_file(self) -> None:
        """Parse Koeppen-Geiger-ASCII.txt and bulk-insert into climates table."""
        # Look for the file relative to the project root (two levels up from this file)
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
            next(fh)  # skip header
            for line in fh:
                parts = line.split()
                if len(parts) < 3:
                    continue
                try:
                    lat, lon, code = float(parts[0]), float(parts[1]), parts[2]
                    rows.append((lat, lon, code))
                except ValueError:
                    continue

        # Batch insert via executemany
        self._conn.executemany(
            "INSERT OR IGNORE INTO climates (lat, lon, code) VALUES (?, ?, ?)", rows
        )
        logger.info("Loaded %d Koeppen-Geiger grid cells", len(rows))

    def lookup_climate(self, lat: float, lon: float) -> str | None:
        """Return the Koeppen-Geiger code for the nearest 0.5° grid cell."""
        if self._conn is None:
            return None
        snapped_lat = _snap_to_koeppen_grid(lat)
        snapped_lon = _snap_to_koeppen_grid(lon)
        result = self._conn.execute(
            "SELECT code FROM climates WHERE lat = ? AND lon = ?",
            [snapped_lat, snapped_lon],
        ).fetchone()
        return result[0] if result else None

    def health_check(self) -> bool:
        try:
            if self._conn is None:
                return False
            self._conn.execute("SELECT 1")
            return True
        except Exception:
            return False

    def save_features(
        self,
        location_key: str,
        processing_version: str,
        date_start: str,
        date_end: str,
        features: dict,
        quality: dict,
    ) -> None:
        if self._conn is None:
            return
        now = datetime.now(timezone.utc).isoformat()
        self._conn.execute(
            """
            INSERT OR REPLACE INTO location_features
                (location_key, processing_version, date_start, date_end, features_json, quality_json, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [location_key, processing_version, date_start, date_end,
             json.dumps(features), json.dumps(quality), now],
        )
        self._conn.commit()

    def get_features(
        self, location_key: str, processing_version: str, date_start: str, date_end: str
    ) -> dict | None:
        if self._conn is None:
            return None
        result = self._conn.execute(
            """
            SELECT features_json, quality_json FROM location_features
            WHERE location_key = ? AND processing_version = ? AND date_start = ? AND date_end = ?
            """,
            [location_key, processing_version, date_start, date_end],
        ).fetchone()
        if result is None:
            return None
        return {"features": json.loads(result[0]), "quality": json.loads(result[1])}

    def save_timeseries(
        self,
        location_key: str,
        processing_version: str,
        cadence: str,
        series: dict,
    ) -> None:
        if self._conn is None:
            return
        now = datetime.now(timezone.utc).isoformat()
        for metric, records in series.items():
            def _to_dict(r):
                if hasattr(r, "model_dump"):
                    return r.model_dump()
                if dataclasses.is_dataclass(r):
                    return dataclasses.asdict(r)
                return r
            serialized = json.dumps([_to_dict(r) for r in records])
            self._conn.execute(
                """
                INSERT OR REPLACE INTO location_timeseries
                    (location_key, processing_version, cadence, metric, series_json, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                [location_key, processing_version, cadence, metric, serialized, now],
            )
        self._conn.commit()

    def save_geometry(
        self,
        location_key: str,
        geojson: dict,
        name: str | None = None,
        customer_id: str | None = None,
    ) -> None:
        if self._conn is None:
            return
        now = datetime.now(timezone.utc).isoformat()
        # Preserve existing name/customer_id if not supplied in this call
        existing = self._conn.execute(
            "SELECT name, customer_id FROM location_geometries WHERE location_key = ?", [location_key]
        ).fetchone()
        if existing:
            if name is None:
                name = existing[0]
            if customer_id is None:
                customer_id = existing[1]
        # Validate customer_id exists before inserting; silently drop if not found
        # (prevents FK violation when callers pass arbitrary customer strings)
        if customer_id is not None:
            exists = self._conn.execute(
                "SELECT 1 FROM customers WHERE customer_id = ?", [customer_id]
            ).fetchone()
            if not exists:
                customer_id = None

        # Derive climate code from centroid if not already stored
        climate_code = None
        if existing:
            existing_code = self._conn.execute(
                "SELECT climate_code FROM location_geometries WHERE location_key = ?",
                [location_key],
            ).fetchone()
            climate_code = existing_code[0] if existing_code else None
        if climate_code is None:
            try:
                pt = shape(geojson)
                climate_code = self.lookup_climate(pt.y, pt.x)
            except Exception:
                pass

        self._conn.execute(
            """
            INSERT OR REPLACE INTO location_geometries
                (location_key, geojson_text, name, customer_id, climate_code, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [location_key, json.dumps(geojson), name, customer_id, climate_code, now],
        )
        self._conn.commit()

    def get_geometry(self, location_key: str) -> dict | None:
        if self._conn is None:
            return None
        result = self._conn.execute(
            "SELECT geojson_text FROM location_geometries WHERE location_key = ?",
            [location_key],
        ).fetchone()
        if result is None:
            return None
        return json.loads(result[0])

    # ------------------------------------------------------------------
    # Customer management
    # ------------------------------------------------------------------

    def create_customer(self, name: str) -> dict:
        """Create a new customer with a random 6-hex-char ID."""
        if self._conn is None:
            raise RuntimeError("DB not connected")
        # Retry on the astronomically unlikely collision
        for _ in range(5):
            customer_id = secrets.token_hex(3)  # 6 hex chars
            existing = self._conn.execute(
                "SELECT customer_id FROM customers WHERE customer_id = ?", [customer_id]
            ).fetchone()
            if existing is None:
                break
        now = datetime.now(timezone.utc).isoformat()
        self._conn.execute(
            "INSERT INTO customers (customer_id, name, created_at) VALUES (?, ?, ?)",
            [customer_id, name, now],
        )
        self._conn.commit()
        return {"customer_id": customer_id, "name": name, "created_at": now}

    def get_customer(self, customer_id: str) -> dict | None:
        if self._conn is None:
            return None
        row = self._conn.execute(
            "SELECT customer_id, name, created_at FROM customers WHERE customer_id = ?",
            [customer_id],
        ).fetchone()
        if row is None:
            return None
        return {
            "customer_id": row[0],
            "name": row[1],
            "created_at": row[2].isoformat() if hasattr(row[2], "isoformat") else str(row[2]),
        }

    def get_all_customers(self) -> list[dict]:
        """Return all customers ordered by name."""
        if self._conn is None:
            return []
        rows = self._conn.execute(
            "SELECT customer_id, name, created_at FROM customers ORDER BY name"
        ).fetchall()
        return [
            {
                "customer_id": row[0],
                "name": row[1],
                "created_at": row[2].isoformat() if hasattr(row[2], "isoformat") else str(row[2]),
            }
            for row in rows
        ]

    def get_customer_locations(self, customer_id: str) -> list[dict]:
        """Return all locations belonging to a customer, most recent first."""
        if self._conn is None:
            return []
        return self._locations_query("WHERE pg.customer_id = ?", [customer_id])

    def _locations_query(self, where: str = "", params: list = []) -> list[dict]:
        """Shared location listing query, optionally filtered."""
        rows = self._conn.execute(
            f"""
            WITH latest_features AS (
                SELECT location_key, processing_version, features_json
                FROM location_features
                QUALIFY ROW_NUMBER() OVER (PARTITION BY location_key ORDER BY updated_at DESC) = 1
            ),
            latest_scores AS (
                SELECT location_key, score_version, scores_json
                FROM location_scores
                QUALIFY ROW_NUMBER() OVER (PARTITION BY location_key ORDER BY updated_at DESC) = 1
            )
            SELECT pg.location_key, pg.geojson_text, pg.name, pg.customer_id,
                   c.name AS customer_name, pg.updated_at,
                   lf.processing_version, ls.score_version,
                   lf.features_json, ls.scores_json
            FROM location_geometries pg
            LEFT JOIN customers c ON pg.customer_id = c.customer_id
            LEFT JOIN latest_features lf ON lf.location_key = pg.location_key
            LEFT JOIN latest_scores ls ON ls.location_key = pg.location_key
            {where}
            ORDER BY pg.updated_at DESC
            """,
            params,
        ).fetchall()
        result = []
        for (location_key, geojson_text, name, customer_id, customer_name,
             updated_at, processing_version, score_version,
             features_json_str, scores_json_str) in rows:
            try:
                geojson = json.loads(geojson_text)
                centroid = shape(geojson).centroid
                centroid_lonlat = [round(centroid.x, 5), round(centroid.y, 5)]
            except Exception:
                centroid_lonlat = None
            quality_score: float | None = None
            composite_score: int | None = None
            if features_json_str:
                try:
                    quality_score = json.loads(features_json_str).get("quality_score")
                except Exception:
                    pass
            if scores_json_str:
                try:
                    composite_score = json.loads(scores_json_str).get("composite_score")
                except Exception:
                    pass
            result.append({
                "location_key": location_key,
                "name": name,
                "customer_id": customer_id,
                "customer_name": customer_name,
                "centroid": centroid_lonlat,
                "updated_at": updated_at.isoformat() if hasattr(updated_at, "isoformat") else str(updated_at),
                "processing_version": processing_version,
                "score_version": score_version,
                "quality_score": quality_score,
                "composite_score": composite_score,
                "report_url": f"/v1/location/{location_key}/report",
                "thumbnail_url": f"/v1/thumbnail/{location_key}.png",
            })
        return result

    def get_all_locations(self) -> list[dict]:
        """Return all stored locations ordered by most recently updated."""
        if self._conn is None:
            return []
        return self._locations_query()

    def get_location_info(self, location_key: str) -> dict | None:
        """Return geometry, name, centroid, and climate info for a location."""
        if self._conn is None:
            return None
        result = self._conn.execute(
            "SELECT geojson_text, name, climate_code FROM location_geometries WHERE location_key = ?",
            [location_key],
        ).fetchone()
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

        # Expand climate code into human-readable descriptions
        climate_info: dict | None = None
        if climate_code:
            label, criterion = _KG_DESCRIPTIONS.get(climate_code, (None, None))
            main_class = _KG_MAIN.get(climate_code[0]) if climate_code else None
            climate_info = {
                "code": climate_code,
                "label": label or climate_code,
                "criterion": criterion,
                "main_class": main_class,
            }

        return {"geojson": geojson, "name": name, "centroid": centroid_lonlat,
                "climate": climate_info}

    def save_scores(
        self,
        location_key: str,
        score_version: str,
        lookback_years: int,
        scores: dict,
    ) -> None:
        if self._conn is None:
            return
        now = datetime.now(timezone.utc).isoformat()
        self._conn.execute(
            """
            INSERT OR REPLACE INTO location_scores
                (location_key, score_version, lookback_years, scores_json, updated_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            [location_key, score_version, lookback_years, json.dumps(scores), now],
        )
        self._conn.commit()

    def get_timeseries(
        self,
        location_key: str,
        processing_version: str,
        cadence: str = "monthly",
    ) -> dict[str, list[dict]] | None:
        """Load all stored time series records for a location."""
        if self._conn is None:
            return None
        rows = self._conn.execute(
            """
            SELECT metric, series_json FROM location_timeseries
            WHERE location_key = ? AND processing_version = ? AND cadence = ?
            """,
            [location_key, processing_version, cadence],
        ).fetchall()
        if not rows:
            return None
        return {metric: json.loads(series_json) for metric, series_json in rows}

    def get_scores(
        self,
        location_key: str,
        score_version: str,
    ) -> dict | None:
        """Load most recent scores for a location."""
        if self._conn is None:
            return None
        result = self._conn.execute(
            """
            SELECT scores_json FROM location_scores
            WHERE location_key = ? AND score_version = ?
            ORDER BY updated_at DESC LIMIT 1
            """,
            [location_key, score_version],
        ).fetchone()
        if result is None:
            return None
        return json.loads(result[0])

    def get_scene_months(
        self,
        location_key: str,
        processing_version: str,
        limit: int = 12,
    ) -> list[dict]:
        """Return up to `limit` most recent scenes with all their band arrays.

        Each entry: {"scene_id": str, "month_key": str, "bands": {band_key: np.ndarray}}
        """
        if self._conn is None:
            return []
        # One scene per month: pick the scene with lowest cloud fraction,
        # excluding scenes that exceed the max allowed cloud cover (invalid scenes).
        max_cloud = 1.0 - settings.MIN_VALID_PIXEL_FRACTION
        scenes = self._conn.execute(
            """
            SELECT scene_id, month_key FROM (
                SELECT scene_id, month_key, MIN(cloud_fraction) AS cf,
                       ROW_NUMBER() OVER (PARTITION BY month_key ORDER BY MIN(cloud_fraction) ASC) AS rn
                FROM scene_bands
                WHERE location_key = ? AND processing_version = ?
                GROUP BY scene_id, month_key
                HAVING MIN(cloud_fraction) <= ?
            )
            WHERE rn = 1
            ORDER BY month_key DESC
            LIMIT ?
            """,
            [location_key, processing_version, max_cloud, limit],
        ).fetchall()
        result = []
        for scene_id, month_key in scenes:
            rows = self._conn.execute(
                """
                SELECT band_key, width, height, data FROM scene_bands
                WHERE location_key = ? AND scene_id = ? AND processing_version = ?
                """,
                [location_key, scene_id, processing_version],
            ).fetchall()
            bands = {
                band_key: np.array(data, dtype=np.float32).reshape(h, w)
                for band_key, w, h, data in rows
            }
            result.append({"scene_id": scene_id, "month_key": month_key, "bands": bands})
        return result

    def store_scene_bands(
        self,
        location_key: str,
        scene_id: str,
        month_key: str,
        processing_version: str,
        bands: dict[str, np.ndarray],
        cloud_fraction: float = 0.0,
    ) -> None:
        """Persist 64×64 band arrays for a scene to DuckDB."""
        if self._conn is None:
            return
        now = datetime.now(timezone.utc).isoformat()
        for band_key, arr in bands.items():
            h, w = arr.shape
            flat = arr.flatten().astype(np.float32).tolist()
            self._conn.execute(
                """
                INSERT OR REPLACE INTO scene_bands
                    (location_key, scene_id, month_key, processing_version,
                     band_key, width, height, data, cloud_fraction, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [location_key, scene_id, month_key, processing_version,
                 band_key, w, h, flat, cloud_fraction, now],
            )

    def load_scene_bands(
        self,
        location_key: str,
        scene_id: str,
        processing_version: str,
        band_keys: list[str],
    ) -> dict[str, np.ndarray] | None:
        """Load stored band arrays for a scene. Returns None if any band is missing."""
        if self._conn is None:
            return None
        rows = self._conn.execute(
            """
            SELECT band_key, width, height, data FROM scene_bands
            WHERE location_key = ? AND scene_id = ? AND processing_version = ?
              AND band_key IN (SELECT unnest(?))
            """,
            [location_key, scene_id, processing_version, band_keys],
        ).fetchall()
        if len(rows) < len(band_keys):
            return None
        result: dict[str, np.ndarray] = {}
        for band_key, w, h, data in rows:
            result[band_key] = np.array(data, dtype=np.float32).reshape(h, w)
        if not all(k in result for k in band_keys):
            return None
        return result

    def delete_scene_bands(
        self,
        location_key: str,
        scene_id: str,
        processing_version: str,
    ) -> None:
        """Remove all band rows for a scene (e.g. when SCL validity check fails)."""
        if self._conn is None:
            return
        self._conn.execute(
            """
            DELETE FROM scene_bands
            WHERE location_key = ? AND scene_id = ? AND processing_version = ?
            """,
            [location_key, scene_id, processing_version],
        )

    def store_sar_scene(
        self,
        location_key: str,
        scene_id: str,
        month_key: str,
        processing_version: str,
        vv_dn: "np.ndarray",
        water_frac: float,
        rel_orbit: int = 0,
    ) -> None:
        """Persist a 64×64 VV uint16 array for one S1 scene."""
        if self._conn is None:
            return
        h, w = vv_dn.shape
        flat = vv_dn.astype(np.float32).flatten().tolist()
        now = datetime.now(timezone.utc).isoformat()
        self._conn.execute(
            """
            INSERT OR REPLACE INTO sar_scene_bands
                (location_key, scene_id, month_key, processing_version,
                 width, height, vv_data, water_frac, rel_orbit, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [location_key, scene_id, month_key, processing_version, w, h, flat, water_frac, rel_orbit, now],
        )
        self._conn.commit()

    def get_sar_scene_months(
        self,
        location_key: str,
        processing_version: str,
        limit: int = 12,
    ) -> list[dict]:
        """Return up to `limit` most recent SAR scenes with VV array and water_frac.

        One scene per month (lowest water_frac first so we show the most
        land-like scene, giving visual context for what is and isn't water).
        Each entry: {"scene_id": str, "month_key": str, "vv_dn": np.ndarray, "water_frac": float}
        """
        if self._conn is None:
            return []
        scenes = self._conn.execute(
            """
            SELECT scene_id, month_key, width, height, vv_data, water_frac
            FROM (
                SELECT scene_id, month_key, width, height, vv_data, water_frac,
                       ROW_NUMBER() OVER (PARTITION BY month_key ORDER BY water_frac ASC) AS rn
                FROM sar_scene_bands
                WHERE location_key = ? AND processing_version = ?
            )
            WHERE rn = 1
            ORDER BY month_key DESC
            LIMIT ?
            """,
            [location_key, processing_version, limit],
        ).fetchall()
        result = []
        for scene_id, month_key, w, h, vv_data, water_frac in scenes:
            vv_dn = np.array(vv_data, dtype=np.float32).reshape(h, w).astype(np.uint16)
            result.append({
                "scene_id": scene_id,
                "month_key": month_key,
                "vv_dn": vv_dn,
                "water_frac": water_frac,
            })
        return result

    def get_sar_scene_fracs(
        self,
        location_key: str,
        processing_version: str,
    ) -> list[tuple[str, float]]:
        """Return all (month_key, water_frac) pairs for SAR scenes, ordered chronologically.

        One entry per scene (not deduplicated by month). Used for time series charting
        and anomaly detection visualisation in the report.
        """
        if self._conn is None:
            return []
        rows = self._conn.execute(
            """
            SELECT month_key, water_frac
            FROM sar_scene_bands
            WHERE location_key = ? AND processing_version = ?
            ORDER BY month_key ASC
            """,
            [location_key, processing_version],
        ).fetchall()
        return [(row[0], row[1]) for row in rows if row[1] is not None]

    def get_sar_scene_fracs_with_orbit(
        self,
        location_key: str,
        processing_version: str,
    ) -> list[tuple[str, float, int]]:
        """Return all (month_key, water_frac, rel_orbit) triples, ordered chronologically.

        Includes orbit number for per-orbit MAD threshold visualization in the report.
        """
        if self._conn is None:
            return []
        rows = self._conn.execute(
            """
            SELECT month_key, water_frac, COALESCE(rel_orbit, 0)
            FROM sar_scene_bands
            WHERE location_key = ? AND processing_version = ?
            ORDER BY month_key ASC
            """,
            [location_key, processing_version],
        ).fetchall()
        return [(row[0], float(row[1]), int(row[2])) for row in rows if row[1] is not None]

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
        """Return {var: {(year, month): value}} for cached TerraClimate rows."""
        if self._conn is None or not variables or not years:
            return {var: {} for var in variables}
        var_ph = ",".join("?" * len(variables))
        year_ph = ",".join("?" * len(years))
        rows = self._conn.execute(
            f"""
            SELECT variable, year, month, value
            FROM terraclimate_monthly
            WHERE grid_lat = CAST(? AS FLOAT) AND grid_lon = CAST(? AS FLOAT)
              AND variable IN ({var_ph})
              AND year IN ({year_ph})
            """,
            [grid_lat, grid_lon] + list(variables) + list(years),
        ).fetchall()
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
        """Persist TerraClimate monthly rows. Each row: {variable, year, month, value}."""
        if self._conn is None or not rows:
            return
        for row in rows:
            self._conn.execute(
                """
                INSERT OR REPLACE INTO terraclimate_monthly
                    (grid_lat, grid_lon, variable, year, month, value)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                [grid_lat, grid_lon, row["variable"], row["year"], row["month"], row["value"]],
            )
        self._conn.commit()

    def get_all_terraclimate_for_grid(
        self,
        grid_lat: float,
        grid_lon: float,
    ) -> dict[str, list[tuple[int, int, float | None]]]:
        """Return all stored TerraClimate data for a grid cell.

        Returns {variable: [(year, month, value), ...]} ordered by year, month.
        Used by the report renderer to build climate charts.
        """
        if self._conn is None:
            return {}
        rows = self._conn.execute(
            """
            SELECT variable, year, month, value
            FROM terraclimate_monthly
            WHERE grid_lat = CAST(? AS FLOAT) AND grid_lon = CAST(? AS FLOAT)
            ORDER BY variable, year, month
            """,
            [grid_lat, grid_lon],
        ).fetchall()
        result: dict[str, list[tuple[int, int, float | None]]] = {}
        for variable, year, month, value in rows:
            result.setdefault(variable, []).append((int(year), int(month), value))
        return result

    def delete_sar_scenes(self, location_key: str, processing_version: str) -> int:
        """Delete all stored SAR scene arrays for a location+version.

        Called before a forced recompute to ensure stale arrays from previous
        pipeline runs (possibly read with a different window geometry) are
        removed before the fresh COG reads are stored.
        """
        if self._conn is None:
            return 0
        result = self._conn.execute(
            "DELETE FROM sar_scene_bands WHERE location_key = ? AND processing_version = ? RETURNING 1",
            [location_key, processing_version],
        ).fetchall()
        self._conn.commit()
        return len(result)

    def delete_location(self, location_key: str) -> dict[str, int]:
        """Delete all data for a location from every table.

        Returns a dict of table → rows deleted.
        """
        if self._conn is None:
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
        for table in tables:
            result = self._conn.execute(
                f"DELETE FROM {table} WHERE location_key = ? RETURNING 1",
                [location_key],
            ).fetchall()
            deleted[table] = len(result)
        self._conn.commit()
        return deleted


store = DuckDBStore()
