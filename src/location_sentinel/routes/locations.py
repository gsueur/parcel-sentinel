from __future__ import annotations

import asyncio
import datetime
import logging
import uuid

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

from ..config import settings
from ..geometry.validate import GeometryValidationError
from ..jobs import job_store
from ..models.requests import LocationRequest
from ..models.responses import LocationResponse
from ..models.common import DateWindow
from ..pipeline.score_pipeline import run_score
from ..storage.cache import cache
from ..storage.duckdb_store import store
from ..geometry.normalize import geojson_to_shapely, make_location_key
from ..thumbnails.links import build_map_links

logger = logging.getLogger(__name__)

router = APIRouter()

_CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
       background: #0f1117; color: #e0e0e0; font-size: 14px; }
.header { padding: 20px 24px 16px; border-bottom: 1px solid #1e2130; }
.header h1 { font-size: 1.3rem; font-weight: 600; color: #fff; }
.header small { color: #6b7280; font-size: 0.8rem; }
.container { max-width: 900px; margin: 0 auto; padding: 24px; }
.card { display: flex; align-items: center; gap: 16px;
        background: #161b27; border: 1px solid #1e2130; border-radius: 8px;
        padding: 16px; margin-bottom: 12px; text-decoration: none;
        transition: border-color 0.15s; }
.card:hover { border-color: #3b82f6; }
.thumb { width: 80px; height: 54px; object-fit: cover; border-radius: 4px;
         background: #1e2130; flex-shrink: 0; }
.thumb-placeholder { width: 80px; height: 54px; border-radius: 4px;
                     background: #1e2130; flex-shrink: 0; }
.info { flex: 1; min-width: 0; }
.name { font-size: 1rem; font-weight: 600; color: #fff;
        white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.coords { font-size: 0.8rem; color: #9ca3af; margin-top: 3px; }
.key  { font-size: 0.72rem; color: #4b5563; font-family: monospace;
        margin-top: 4px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.updated { font-size: 0.75rem; color: #4b5563; flex-shrink: 0; text-align: right; }
.empty { color: #4b5563; font-style: italic; padding: 24px 0; }
"""


@router.post("/locations", status_code=202)
async def create_location(req: LocationRequest):
    """Submit a location for async computation. Returns a job_id to poll via GET /v1/jobs/{job_id}."""
    try:
        geom = geojson_to_shapely(req.geometry.model_dump())
    except GeometryValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    centroid = geom.centroid
    stable_key = make_location_key(
        name=req.name,
        centroid=(centroid.x, centroid.y),
        customer_id=req.customer_id,
    )

    existing = job_store.find_active(stable_key)
    if existing:
        return {"job_id": existing.job_id, "status": existing.status}

    job = job_store.create(stable_key)
    asyncio.create_task(_run_location_job(job.job_id, req, stable_key))
    return {"job_id": job.job_id, "status": "pending"}


async def _run_location_job(job_id: str, req: LocationRequest, stable_key: str) -> None:
    trace_id = uuid.uuid4().hex[:12]
    de = req.date_end.isoformat()

    cache_key = (
        f"location|{stable_key}"
        f"|{de}|{req.lookback_years}"
        f"|{settings.SCORE_VERSION}|{settings.PROCESSING_VERSION}"
    )

    if not req.force_recompute:
        cached = cache.get(cache_key)
        if cached is not None:
            job_store.update(job_id, status="ready", location_key=stable_key,
                             report_url=f"/v1/location/{stable_key}/report", name=req.name)
            return

    job_store.update(job_id, status="running")

    if req.force_recompute:
        # Purge stale SAR scene arrays so the pipeline re-downloads fresh COGs.
        # Without this, INSERT OR REPLACE only updates rows for scene_ids that
        # appear in the new STAC search; any scene whose COG read fails silently
        # would leave the old (possibly misaligned) array in place.
        n_deleted = store.delete_sar_scenes(stable_key, settings.PROCESSING_VERSION)
        if n_deleted:
            logger.info("force_recompute: purged %d stale SAR scenes for %s", n_deleted, stable_key)

    try:
        location_key, score_result, features, quality, date_start, series = await run_score(
            geom_geojson=req.geometry.model_dump(),
            date_end=de,
            lookback_years=req.lookback_years,
            location_key=stable_key,
        )
    except GeometryValidationError as e:
        job_store.update(job_id, status="failed", error=str(e))
        return
    except ValueError as e:
        job_store.update(job_id, status="failed", error=str(e))
        return
    except Exception:
        logger.exception("Computation failed trace_id=%s", trace_id)
        job_store.update(job_id, status="failed", error=f"Computation failed (trace_id={trace_id})")
        return

    geom_dict = req.geometry.model_dump()
    store.save_geometry(location_key, geom_dict, name=req.name, customer_id=req.customer_id)
    store.save_scores(location_key, settings.SCORE_VERSION, req.lookback_years, {
        "drought_score": score_result.drought_score,
        "wetness_score": score_result.wetness_score,
        "fire_exposure_score": score_result.fire_exposure_score,
        "heat_mitigation_score": score_result.heat_mitigation_score,
        "flood_risk_score": score_result.flood_risk_score,
        "heat_stress_score": score_result.heat_stress_score,
        "composite_score": score_result.composite_score,
    })
    store.save_features(location_key, settings.PROCESSING_VERSION, date_start, de,
                        features, quality.model_dump())
    store.save_timeseries(location_key, settings.PROCESSING_VERSION, "monthly", series)

    response = LocationResponse(
        location_key=location_key,
        name=req.name,
        processing_version=settings.PROCESSING_VERSION,
        score_version=settings.SCORE_VERSION,
        date_window=DateWindow(start=date_start, end=de),
        scores={
            "drought_score": score_result.drought_score,
            "wetness_score": score_result.wetness_score,
            "fire_exposure_score": score_result.fire_exposure_score,
            "heat_mitigation_score": score_result.heat_mitigation_score,
            "flood_risk_score": score_result.flood_risk_score,
            "heat_stress_score": score_result.heat_stress_score,
            "composite_score": score_result.composite_score,
        },
        features=features,
        quality=quality,
        map_links=build_map_links(location_key, geom_dict),
    )
    cache.set(cache_key, response)
    job_store.update(job_id, status="ready", location_key=location_key,
                     report_url=f"/v1/location/{location_key}/report", name=req.name)


class _RegenerateRequest(BaseModel):
    date_end: datetime.date = Field(default_factory=datetime.date.today)
    lookback_years: int = Field(default=5, ge=1, le=10)


@router.post("/location/{location_key}/regenerate", status_code=202)
async def regenerate_location(location_key: str, req: _RegenerateRequest = _RegenerateRequest()):
    """Submit regeneration as an async job. Returns job_id to poll via GET /v1/jobs/{job_id}.

    The location_key is preserved exactly -- no re-derivation from geometry.
    Use this instead of re-POSTing to /locations to avoid creating duplicate entries.
    """
    location_info = store.get_location_info(location_key)
    if location_info is None:
        raise HTTPException(status_code=404, detail=f"Location {location_key!r} not found")

    existing = job_store.find_active(location_key)
    if existing:
        return {"job_id": existing.job_id, "status": existing.status}

    job = job_store.create(location_key)
    asyncio.create_task(_run_regenerate_job(job.job_id, location_key, location_info, req))
    return {"job_id": job.job_id, "status": "pending"}


async def _run_regenerate_job(
    job_id: str,
    location_key: str,
    location_info: dict,
    req: _RegenerateRequest,
) -> None:
    trace_id = uuid.uuid4().hex[:12]
    geom_dict = location_info["geojson"]
    name = location_info["name"]
    de = req.date_end.isoformat()

    job_store.update(job_id, status="running")

    try:
        _lk, score_result, features, quality, date_start, series = await run_score(
            geom_geojson=geom_dict,
            date_end=de,
            lookback_years=req.lookback_years,
            location_key=location_key,
        )
    except Exception:
        logger.exception("Regeneration failed location_key=%s trace_id=%s", location_key, trace_id)
        job_store.update(job_id, status="failed", error=f"Computation failed (trace_id={trace_id})")
        return

    store.save_geometry(location_key, geom_dict, name=name)
    store.save_scores(location_key, settings.SCORE_VERSION, req.lookback_years, {
        "drought_score": score_result.drought_score,
        "wetness_score": score_result.wetness_score,
        "fire_exposure_score": score_result.fire_exposure_score,
        "heat_mitigation_score": score_result.heat_mitigation_score,
        "flood_risk_score": score_result.flood_risk_score,
        "heat_stress_score": score_result.heat_stress_score,
        "composite_score": score_result.composite_score,
    })
    store.save_features(location_key, settings.PROCESSING_VERSION, date_start, de,
                        features, quality.model_dump())
    store.save_timeseries(location_key, settings.PROCESSING_VERSION, "monthly", series)
    cache.clear()

    job_store.update(job_id, status="ready", location_key=location_key,
                     report_url=f"/v1/location/{location_key}/report", name=name)


@router.delete("/location/{location_key}")
async def delete_location(location_key: str):
    """Delete all stored data for a location (features, scores, timeseries, scene bands, geometry).

    Returns a summary of rows deleted per table.
    Idempotent: deleting an unknown key returns zeros without error.
    """
    deleted = store.delete_location(location_key)
    cache.clear()  # evict any cached responses for this key
    return {"location_key": location_key, "deleted": deleted}



@router.get("/locations")
async def list_locations(format: str = Query(default="json", pattern="^(json|html)$")):
    """List all stored locations.

    Returns JSON by default. Pass ?format=html for a browsable index page
    with thumbnail previews and links to individual reports.
    """
    locations = store.get_all_locations()

    if format == "html":
        return HTMLResponse(content=_build_html(locations))

    return JSONResponse(content={
        "count": len(locations),
        "server_versions": {
            "processing": settings.PROCESSING_VERSION,
            "score": settings.SCORE_VERSION,
        },
        "locations": locations,
    })


def _build_html(locations: list[dict]) -> str:
    if not locations:
        cards = '<p class="empty">No locations computed yet.</p>'
    else:
        rows = []
        for p in locations:
            name = p["name"] or "Unnamed location"
            coords = ""
            if p["centroid"]:
                lon, lat = p["centroid"]
                coords = f"&#x1F4CD; {lat:+.5f}, {lon:+.5f}"
            key_short = p["location_key"][:32] + "..."
            updated = p["updated_at"][:16].replace("T", " ") if p["updated_at"] else ""
            rows.append(f"""
            <a class="card" href="{p['report_url']}">
              <img class="thumb" src="{p['thumbnail_url']}"
                   alt="" onerror="this.className='thumb-placeholder'">
              <div class="info">
                <div class="name">{name}</div>
                <div class="coords">{coords}</div>
                <div class="key">{key_short}</div>
              </div>
              <div class="updated">{updated}</div>
            </a>""")
        cards = "\n".join(rows)

    count = len(locations)
    noun = "location" if count == 1 else "locations"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Location Sentinel &mdash; Locations</title>
  <style>{_CSS}</style>
</head>
<body>
  <div class="header">
    <h1>Locations</h1>
    <small>{count} {noun} stored</small>
  </div>
  <div class="container">
    {cards}
  </div>
</body>
</html>"""
