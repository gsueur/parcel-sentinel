from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse

from ..config import settings
from ..report.html import build_report_html
from ..storage.duckdb_store import store

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/parcel/{parcel_key}/report", response_class=HTMLResponse)
async def get_parcel_report(parcel_key: str):
    """Return a full HTML report for a previously computed parcel.

    The parcel_key must correspond to at least one prior POST request
    (geometry must be stored in DuckDB). Other sections (scores, features,
    timeseries, scene images) are included if already computed and cached.
    """
    geometry = store.get_geometry(parcel_key)
    if geometry is None:
        raise HTTPException(
            status_code=404,
            detail=f"Parcel {parcel_key!r} not found. Run a POST request first to compute and store results.",
        )

    # Load all available stored data — each section is optional
    features_data = store.get_features(
        parcel_key, settings.PROCESSING_VERSION,
        date_start="", date_end="",  # load any stored version
    )
    # Broad query: try to find any stored features regardless of exact date window
    if features_data is None:
        features_data = _get_any_features(parcel_key)

    scores = store.get_scores(parcel_key, settings.SCORE_VERSION)
    timeseries = store.get_timeseries(parcel_key, settings.PROCESSING_VERSION)
    scene_months = store.get_scene_months(parcel_key, settings.PROCESSING_VERSION, limit=12)

    features = features_data.get("features") if features_data else None
    quality = features_data.get("quality") if features_data else None

    html = build_report_html(
        parcel_key=parcel_key,
        geometry_geojson=geometry,
        scores=scores,
        features=features,
        quality=quality,
        timeseries=timeseries,
        scene_months=scene_months,
        processing_version=settings.PROCESSING_VERSION,
        score_version=settings.SCORE_VERSION,
    )

    return HTMLResponse(content=html, status_code=200)


def _get_any_features(parcel_key: str) -> dict | None:
    """Retrieve the most recent features row regardless of date window."""
    if store._conn is None:
        return None
    import json
    result = store._conn.execute(
        """
        SELECT features_json, quality_json FROM parcel_features
        WHERE parcel_key = ?
        ORDER BY updated_at DESC LIMIT 1
        """,
        [parcel_key],
    ).fetchone()
    if result is None:
        return None
    return {"features": json.loads(result[0]), "quality": json.loads(result[1])}
