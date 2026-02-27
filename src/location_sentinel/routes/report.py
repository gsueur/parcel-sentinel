from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse

from ..config import settings
from ..report.html import build_report_html
from ..stac.terraclimate_client import snap_to_grid
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
    sar_scene_months = store.get_sar_scene_months(location_key, settings.PROCESSING_VERSION, limit=12)
    sar_scene_fracs = store.get_sar_scene_fracs_with_orbit(location_key, settings.PROCESSING_VERSION)

    # TerraClimate monthly data for climate charts (served from DuckDB cache)
    tc_monthly = None
    centroid = location_info.get("centroid")
    if centroid:
        try:
            lon, lat = centroid
            grid_lat, grid_lon = snap_to_grid(lat, lon)
            tc_monthly = store.get_all_terraclimate_for_grid(grid_lat, grid_lon)
        except Exception as exc:
            logger.warning("Could not load TerraClimate data for report: %s", exc)

    # Derive burn months from stored NBR timeseries for SAR chart annotation.
    # Use the same consecutive-month requirement as the pipeline so that the
    # chart shows exactly the months that were suppressed from SAR analysis.
    burn_months: set[str] = set()
    if timeseries and "nbr" in timeseries:
        nbr_recs = sorted(
            [r for r in timeseries["nbr"] if r.get("mean") is not None],
            key=lambda r: r["month"],
        )
        is_burn = [r["mean"] < settings.NBR_BURN_THRESHOLD for r in nbr_recs]

        def _next_month(m: str) -> str:
            y, mo = int(m[:4]), int(m[5:7])
            mo += 1
            if mo > 12:
                mo, y = 1, y + 1
            return f"{y:04d}-{mo:02d}"

        i = 0
        while i < len(nbr_recs):
            if not is_burn[i]:
                i += 1
                continue
            run_start = i
            j = i + 1
            while (
                j < len(nbr_recs)
                and is_burn[j]
                and nbr_recs[j]["month"] == _next_month(nbr_recs[j - 1]["month"])
            ):
                j += 1
            if j - run_start >= settings.NBR_MIN_CONSECUTIVE:
                for k in range(run_start, j):
                    burn_months.add(nbr_recs[k]["month"])
            i = j

    html = build_report_html(
        location_key=location_key,
        name=location_info["name"],
        centroid=centroid,
        geometry_geojson=location_info["geojson"],
        climate=location_info.get("climate"),
        scores=scores,
        features=features_data.get("features") if features_data else None,
        quality=features_data.get("quality") if features_data else None,
        timeseries=timeseries,
        scene_months=scene_months,
        sar_scene_months=sar_scene_months,
        sar_scene_fracs=sar_scene_fracs,
        processing_version=settings.PROCESSING_VERSION,
        score_version=settings.SCORE_VERSION,
        tc_monthly=tc_monthly or {},
        burn_months=burn_months or None,
    )

    headers = {"Cache-Control": "no-store"} if settings.ENV == "development" else {}
    return HTMLResponse(content=html, status_code=200, headers=headers)


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
