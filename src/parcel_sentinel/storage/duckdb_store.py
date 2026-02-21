from __future__ import annotations

import json
import logging
import secrets
from datetime import datetime, timezone

import duckdb
import numpy as np
from shapely.geometry import shape

from ..config import settings

logger = logging.getLogger(__name__)


class DuckDBStore:
    """DuckDB persistence layer for parcel features, timeseries, and scores."""

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
            CREATE TABLE IF NOT EXISTS parcel_features (
                parcel_key VARCHAR,
                processing_version VARCHAR,
                date_start VARCHAR,
                date_end VARCHAR,
                features_json VARCHAR,
                quality_json VARCHAR,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (parcel_key, processing_version, date_start, date_end)
            )
        """)
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS parcel_timeseries (
                parcel_key VARCHAR,
                processing_version VARCHAR,
                cadence VARCHAR,
                metric VARCHAR,
                series_json VARCHAR,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (parcel_key, processing_version, cadence, metric)
            )
        """)
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS parcel_scores (
                parcel_key VARCHAR,
                score_version VARCHAR,
                lookback_years INTEGER,
                scores_json VARCHAR,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (parcel_key, score_version, lookback_years)
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
            CREATE TABLE IF NOT EXISTS parcel_geometries (
                parcel_key VARCHAR PRIMARY KEY,
                geojson_text VARCHAR,
                name VARCHAR,
                customer_id VARCHAR REFERENCES customers(customer_id),
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # Migrations for existing databases
        for col_def in [
            "ALTER TABLE parcel_geometries ADD COLUMN IF NOT EXISTS name VARCHAR",
            "ALTER TABLE parcel_geometries ADD COLUMN IF NOT EXISTS customer_id VARCHAR",
        ]:
            try:
                self._conn.execute(col_def)
            except Exception:
                pass
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS scene_bands (
                parcel_key VARCHAR NOT NULL,
                scene_id VARCHAR NOT NULL,
                month_key VARCHAR NOT NULL,
                processing_version VARCHAR NOT NULL,
                band_key VARCHAR NOT NULL,
                width UTINYINT NOT NULL DEFAULT 64,
                height UTINYINT NOT NULL DEFAULT 64,
                data FLOAT[4096] NOT NULL,
                cloud_fraction DOUBLE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (parcel_key, scene_id, processing_version, band_key)
            )
        """)

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
        parcel_key: str,
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
            INSERT OR REPLACE INTO parcel_features
                (parcel_key, processing_version, date_start, date_end, features_json, quality_json, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [parcel_key, processing_version, date_start, date_end,
             json.dumps(features), json.dumps(quality), now],
        )

    def get_features(
        self, parcel_key: str, processing_version: str, date_start: str, date_end: str
    ) -> dict | None:
        if self._conn is None:
            return None
        result = self._conn.execute(
            """
            SELECT features_json, quality_json FROM parcel_features
            WHERE parcel_key = ? AND processing_version = ? AND date_start = ? AND date_end = ?
            """,
            [parcel_key, processing_version, date_start, date_end],
        ).fetchone()
        if result is None:
            return None
        return {"features": json.loads(result[0]), "quality": json.loads(result[1])}

    def save_timeseries(
        self,
        parcel_key: str,
        processing_version: str,
        cadence: str,
        series: dict,
    ) -> None:
        if self._conn is None:
            return
        now = datetime.now(timezone.utc).isoformat()
        for metric, records in series.items():
            serialized = json.dumps([r.model_dump() if hasattr(r, "model_dump") else r for r in records])
            self._conn.execute(
                """
                INSERT OR REPLACE INTO parcel_timeseries
                    (parcel_key, processing_version, cadence, metric, series_json, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                [parcel_key, processing_version, cadence, metric, serialized, now],
            )

    def save_geometry(
        self,
        parcel_key: str,
        geojson: dict,
        name: str | None = None,
        customer_id: str | None = None,
    ) -> None:
        if self._conn is None:
            return
        now = datetime.now(timezone.utc).isoformat()
        # Preserve existing name/customer_id if not supplied in this call
        existing = self._conn.execute(
            "SELECT name, customer_id FROM parcel_geometries WHERE parcel_key = ?", [parcel_key]
        ).fetchone()
        if existing:
            if name is None:
                name = existing[0]
            if customer_id is None:
                customer_id = existing[1]
        self._conn.execute(
            """
            INSERT OR REPLACE INTO parcel_geometries
                (parcel_key, geojson_text, name, customer_id, updated_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            [parcel_key, json.dumps(geojson), name, customer_id, now],
        )

    def get_geometry(self, parcel_key: str) -> dict | None:
        if self._conn is None:
            return None
        result = self._conn.execute(
            "SELECT geojson_text FROM parcel_geometries WHERE parcel_key = ?",
            [parcel_key],
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

    def get_customer_parcels(self, customer_id: str) -> list[dict]:
        """Return all parcels belonging to a customer, most recent first."""
        if self._conn is None:
            return []
        return self._parcels_query("WHERE pg.customer_id = ?", [customer_id])

    def _parcels_query(self, where: str = "", params: list = []) -> list[dict]:
        """Shared parcel listing query, optionally filtered."""
        rows = self._conn.execute(
            f"""
            SELECT pg.parcel_key, pg.geojson_text, pg.name, pg.customer_id,
                   c.name AS customer_name, pg.updated_at
            FROM parcel_geometries pg
            LEFT JOIN customers c ON pg.customer_id = c.customer_id
            {where}
            ORDER BY pg.updated_at DESC
            """,
            params,
        ).fetchall()
        result = []
        for parcel_key, geojson_text, name, customer_id, customer_name, updated_at in rows:
            try:
                geojson = json.loads(geojson_text)
                centroid = shape(geojson).centroid
                centroid_lonlat = [round(centroid.x, 5), round(centroid.y, 5)]
            except Exception:
                centroid_lonlat = None
            result.append({
                "parcel_key": parcel_key,
                "name": name,
                "customer_id": customer_id,
                "customer_name": customer_name,
                "centroid": centroid_lonlat,
                "updated_at": updated_at.isoformat() if hasattr(updated_at, "isoformat") else str(updated_at),
                "report_url": f"/v1/parcel/{parcel_key}/report",
                "thumbnail_url": f"/v1/thumbnail/{parcel_key}.png",
            })
        return result

    def get_all_parcels(self) -> list[dict]:
        """Return all stored parcels ordered by most recently updated."""
        if self._conn is None:
            return []
        return self._parcels_query()

    def get_parcel_info(self, parcel_key: str) -> dict | None:
        """Return geometry, name, and centroid for a parcel, or None if not found."""
        if self._conn is None:
            return None
        result = self._conn.execute(
            "SELECT geojson_text, name FROM parcel_geometries WHERE parcel_key = ?",
            [parcel_key],
        ).fetchone()
        if result is None:
            return None
        geojson = json.loads(result[0])
        name = result[1]
        try:
            centroid = shape(geojson).centroid
            centroid_lonlat = [round(centroid.x, 5), round(centroid.y, 5)]
        except Exception:
            centroid_lonlat = None
        return {"geojson": geojson, "name": name, "centroid": centroid_lonlat}

    def save_scores(
        self,
        parcel_key: str,
        score_version: str,
        lookback_years: int,
        scores: dict,
    ) -> None:
        if self._conn is None:
            return
        now = datetime.now(timezone.utc).isoformat()
        self._conn.execute(
            """
            INSERT OR REPLACE INTO parcel_scores
                (parcel_key, score_version, lookback_years, scores_json, updated_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            [parcel_key, score_version, lookback_years, json.dumps(scores), now],
        )


    def get_timeseries(
        self,
        parcel_key: str,
        processing_version: str,
        cadence: str = "monthly",
    ) -> dict[str, list[dict]] | None:
        """Load all stored time series records for a parcel."""
        if self._conn is None:
            return None
        rows = self._conn.execute(
            """
            SELECT metric, series_json FROM parcel_timeseries
            WHERE parcel_key = ? AND processing_version = ? AND cadence = ?
            """,
            [parcel_key, processing_version, cadence],
        ).fetchall()
        if not rows:
            return None
        return {metric: json.loads(series_json) for metric, series_json in rows}

    def get_scores(
        self,
        parcel_key: str,
        score_version: str,
    ) -> dict | None:
        """Load most recent scores for a parcel."""
        if self._conn is None:
            return None
        result = self._conn.execute(
            """
            SELECT scores_json FROM parcel_scores
            WHERE parcel_key = ? AND score_version = ?
            ORDER BY updated_at DESC LIMIT 1
            """,
            [parcel_key, score_version],
        ).fetchone()
        if result is None:
            return None
        return json.loads(result[0])

    def get_scene_months(
        self,
        parcel_key: str,
        processing_version: str,
        limit: int = 12,
    ) -> list[dict]:
        """Return up to `limit` most recent scenes with all their band arrays.

        Each entry: {"scene_id": str, "month_key": str, "bands": {band_key: np.ndarray}}
        """
        if self._conn is None:
            return []
        # Get distinct (scene_id, month_key) ordered by month desc
        scenes = self._conn.execute(
            """
            SELECT DISTINCT scene_id, month_key FROM scene_bands
            WHERE parcel_key = ? AND processing_version = ?
            ORDER BY month_key DESC
            LIMIT ?
            """,
            [parcel_key, processing_version, limit],
        ).fetchall()
        result = []
        for scene_id, month_key in scenes:
            rows = self._conn.execute(
                """
                SELECT band_key, width, height, data FROM scene_bands
                WHERE parcel_key = ? AND scene_id = ? AND processing_version = ?
                """,
                [parcel_key, scene_id, processing_version],
            ).fetchall()
            bands = {
                band_key: np.array(data, dtype=np.float32).reshape(h, w)
                for band_key, w, h, data in rows
            }
            result.append({"scene_id": scene_id, "month_key": month_key, "bands": bands})
        return result

    def store_scene_bands(
        self,
        parcel_key: str,
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
                    (parcel_key, scene_id, month_key, processing_version,
                     band_key, width, height, data, cloud_fraction, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [parcel_key, scene_id, month_key, processing_version,
                 band_key, w, h, flat, cloud_fraction, now],
            )

    def load_scene_bands(
        self,
        parcel_key: str,
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
            WHERE parcel_key = ? AND scene_id = ? AND processing_version = ?
              AND band_key IN (SELECT unnest(?))
            """,
            [parcel_key, scene_id, processing_version, band_keys],
        ).fetchall()
        if len(rows) < len(band_keys):
            return None
        result: dict[str, np.ndarray] = {}
        for band_key, w, h, data in rows:
            result[band_key] = np.array(data, dtype=np.float32).reshape(h, w)
        if not all(k in result for k in band_keys):
            return None
        return result


store = DuckDBStore()
