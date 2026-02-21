from __future__ import annotations

import json
import logging

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse

from ..config import settings
from ..report.html import build_report_html
from ..storage.duckdb_store import store

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/location/{location_key}/report", response_class=HTMLResponse)
async def get_location_report(location_key: str):
    """Return a full HTML report for a previously computed location."""
    location_info = store.get_location_info(location_key)
    if location_info is None:
        raise HTTPException(
            status_code=404,
            detail=f"Location {location_key!r} not found. Run a POST request first.",
        )

    features_data = _get_any_features(location_key)
    scores = store.get_scores(location_key, settings.SCORE_VERSION)
    timeseries = store.get_timeseries(location_key, settings.PROCESSING_VERSION)
    scene_months = store.get_scene_months(location_key, settings.PROCESSING_VERSION, limit=12)

    html = build_report_html(
        location_key=location_key,
        name=location_info["name"],
        centroid=location_info["centroid"],
        geometry_geojson=location_info["geojson"],
        scores=scores,
        features=features_data.get("features") if features_data else None,
        quality=features_data.get("quality") if features_data else None,
        timeseries=timeseries,
        scene_months=scene_months,
        processing_version=settings.PROCESSING_VERSION,
        score_version=settings.SCORE_VERSION,
    )

    return HTMLResponse(content=html, status_code=200)


def _get_any_features(location_key: str) -> dict | None:
    """Retrieve the most recent features row regardless of date window."""
    if store._conn is None:
        return None
    result = store._conn.execute(
        """
        SELECT features_json, quality_json FROM location_features
        WHERE location_key = ?
        ORDER BY updated_at DESC LIMIT 1
        """,
        [location_key],
    ).fetchone()
    if result is None:
        return None
    import json
    return {"features": json.loads(result[0]), "quality": json.loads(result[1])}
