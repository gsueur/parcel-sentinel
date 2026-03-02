from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse

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
    nearest_tidal = None
    centroid = location_info.get("centroid")
    if centroid:
        try:
            lon, lat = centroid
            grid_lat, grid_lon = snap_to_grid(lat, lon)
            tc_monthly = store.get_all_terraclimate_for_grid(grid_lat, grid_lon)
        except Exception as exc:
            logger.warning("Could not load TerraClimate data for report: %s", exc)
        try:
            lon, lat = centroid
            nearest_tidal = store.get_nearest_tidal_station(lat, lon, settings.TIDAL_ZONE_RADIUS_KM)
        except Exception as exc:
            logger.warning("Could not look up tidal station for report: %s", exc)

    # Derive burn months for SAR chart annotation using the same anomaly-based
    # logic as the pipeline. Months where NBR drops more than NBR_ANOMALY_THRESHOLD
    # below the site's own seasonal climatology, in runs of >= NBR_MIN_CONSECUTIVE
    # calendar-consecutive months, are annotated as burn-suppressed.
    # Anomaly-based (not absolute) so that Mediterranean dry seasons don't trigger.
    burn_months: set[str] = set()
    if timeseries and "nbr" in timeseries:
        nbr_recs = sorted(
            [r for r in timeseries["nbr"] if r.get("mean") is not None],
            key=lambda r: r["month"],
        )
        if nbr_recs:
            # Build seasonal climatology
            by_cal: dict[int, list[float]] = {}
            for r in nbr_recs:
                mo = int(r["month"][5:7])
                by_cal.setdefault(mo, []).append(r["mean"])
            climatology = {mo: sum(v) / len(v) for mo, v in by_cal.items()}

            # Anomaly flag per month
            is_anom = [
                (r["mean"] - climatology.get(int(r["month"][5:7]), r["mean"])) < -settings.NBR_ANOMALY_THRESHOLD
                for r in nbr_recs
            ]

            def _next_month(m: str) -> str:
                y, mo = int(m[:4]), int(m[5:7])
                mo += 1
                if mo > 12:
                    mo, y = 1, y + 1
                return f"{y:04d}-{mo:02d}"

            i = 0
            while i < len(nbr_recs):
                if not is_anom[i]:
                    i += 1
                    continue
                run_start = i
                j = i + 1
                while (
                    j < len(nbr_recs)
                    and is_anom[j]
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
        date_start=features_data.get("date_start") if features_data else None,
        date_end=features_data.get("date_end") if features_data else None,
        timeseries=timeseries,
        scene_months=scene_months,
        sar_scene_months=sar_scene_months,
        sar_scene_fracs=sar_scene_fracs,
        processing_version=settings.PROCESSING_VERSION,
        score_version=settings.SCORE_VERSION,
        tc_monthly=tc_monthly or {},
        burn_months=burn_months or None,
        nearest_tidal=nearest_tidal,
    )

    headers = {"Cache-Control": "no-store"} if settings.ENV == "development" else {}
    return HTMLResponse(content=html, status_code=200, headers=headers)


@router.get("/location/{location_key}/report.json")
async def get_location_report_json(location_key: str):
    """Return the full report data as JSON (same payload as the HTML report, without image arrays)."""
    location_info = store.get_location_info(location_key)
    if location_info is None:
        raise HTTPException(
            status_code=404,
            detail=f"Location {location_key!r} not found. Run a POST request first.",
        )

    features_data = _get_any_features(location_key)
    scores = store.get_scores(location_key, settings.SCORE_VERSION)
    timeseries = store.get_timeseries(location_key, settings.PROCESSING_VERSION)
    sar_scene_months = store.get_sar_scene_months(location_key, settings.PROCESSING_VERSION, limit=12)
    sar_scene_fracs = store.get_sar_scene_fracs_with_orbit(location_key, settings.PROCESSING_VERSION)

    tc_monthly = None
    nearest_tidal_json = None
    centroid = location_info.get("centroid")
    if centroid:
        try:
            lon, lat = centroid
            grid_lat, grid_lon = snap_to_grid(lat, lon)
            tc_monthly = store.get_all_terraclimate_for_grid(grid_lat, grid_lon)
        except Exception as exc:
            logger.warning("Could not load TerraClimate data for report.json: %s", exc)
        try:
            lon, lat = centroid
            nearest_tidal_json = store.get_nearest_tidal_station(lat, lon, settings.TIDAL_ZONE_RADIUS_KM)
        except Exception as exc:
            logger.warning("Could not look up tidal station for report.json: %s", exc)

    # SAR scene metadata without pixel arrays
    sar_scenes = [
        {
            "scene_id": s["scene_id"],
            "month_key": s["month_key"],
            "rel_orbit": s["rel_orbit"],
            "water_frac": s["water_frac"],
        }
        for s in sar_scene_months
    ]

    payload = {
        "location_key": location_key,
        "name": location_info.get("name"),
        "centroid": centroid,
        "geometry": location_info.get("geojson"),
        "climate": location_info.get("climate"),
        "processing_version": settings.PROCESSING_VERSION,
        "score_version": settings.SCORE_VERSION,
        "date_window": {
            "start": features_data.get("date_start") if features_data else None,
            "end": features_data.get("date_end") if features_data else None,
        },
        "scores": scores,
        "features": features_data.get("features") if features_data else None,
        "quality": features_data.get("quality") if features_data else None,
        "timeseries": timeseries,
        "sar_scene_fracs": [
            {"month_key": mk, "water_frac": wf, "rel_orbit": orb}
            for mk, wf, orb in (sar_scene_fracs or [])
        ],
        "sar_scenes": sar_scenes,
        "tc_monthly": tc_monthly,
        "nearest_tidal_station": nearest_tidal_json,
        "map_links": {
            "report_url": f"/v1/location/{location_key}/report",
            "thumbnail_url": f"/v1/thumbnail/{location_key}.png",
        },
    }

    headers = {"Cache-Control": "no-store"} if settings.ENV == "development" else {}
    return JSONResponse(content=payload, status_code=200, headers=headers)


def _get_any_features(location_key: str) -> dict | None:
    """Retrieve the most recent features row regardless of date window."""
    if store._conn is None:
        return None
    result = store._conn.execute(
        """
        SELECT features_json, quality_json, date_start, date_end FROM location_features
        WHERE location_key = ?
        ORDER BY updated_at DESC LIMIT 1
        """,
        [location_key],
    ).fetchone()
    if result is None:
        return None
    import json
    return {
        "features": json.loads(result[0]),
        "quality": json.loads(result[1]),
        "date_start": str(result[2]) if result[2] else None,
        "date_end": str(result[3]) if result[3] else None,
    }
