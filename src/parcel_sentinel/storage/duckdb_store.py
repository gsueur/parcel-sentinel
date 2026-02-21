from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

import duckdb
import numpy as np

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
            CREATE TABLE IF NOT EXISTS parcel_geometries (
                parcel_key VARCHAR PRIMARY KEY,
                geojson_text VARCHAR,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
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

    def save_geometry(self, parcel_key: str, geojson: dict) -> None:
        if self._conn is None:
            return
        now = datetime.now(timezone.utc).isoformat()
        self._conn.execute(
            """
            INSERT OR REPLACE INTO parcel_geometries
                (parcel_key, geojson_text, updated_at)
            VALUES (?, ?, ?)
            """,
            [parcel_key, json.dumps(geojson), now],
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
