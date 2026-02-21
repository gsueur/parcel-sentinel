from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, HTTPException

from ..config import settings
from ..geometry.validate import GeometryValidationError
from ..models.common import CacheInfo, MonthRecord
from ..models.requests import TimeseriesRequest
from ..models.responses import TimeseriesResponse
from ..pipeline.timeseries import run_timeseries
from ..storage.cache import cache
from ..thumbnails.links import build_map_links

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/parcel/timeseries", response_model=TimeseriesResponse)
async def post_timeseries(req: TimeseriesRequest):
    trace_id = uuid.uuid4().hex[:12]

    ds = req.date_start.isoformat()
    de = req.date_end.isoformat()

    cache_key = (
        f"ts|{req.geometry.model_dump_json()}"
        f"|{ds}|{de}"
        f"|{','.join(m.value for m in req.metrics)}"
        f"|{req.cadence.value}"
        f"|{settings.PROCESSING_VERSION}"
    )

    if not req.force_recompute:
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

    try:
        parcel_key, series, quality = await run_timeseries(
            geom_geojson=req.geometry.model_dump(),
            date_start=ds,
            date_end=de,
            metrics=req.metrics,
            max_scenes_per_month=req.max_scenes_per_month,
        )
    except GeometryValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Computation failed trace_id=%s", trace_id)
        raise HTTPException(status_code=500, detail=f"Computation failed (trace_id={trace_id})")

    # Convert MonthlyRecord to MonthRecord for response
    response_series: dict[str, list[MonthRecord]] = {}
    for metric_key, records in series.items():
        response_series[metric_key] = [
            MonthRecord(
                month=r.month,
                mean=r.mean,
                obs=r.obs_count,
                cloud=r.cloud_fraction,
            )
            for r in records
        ]

    geom_dict = req.geometry.model_dump()

    from ..storage.duckdb_store import store
    store.save_geometry(parcel_key, geom_dict, name=req.name, customer_id=req.customer_id)

    map_links = build_map_links(parcel_key, geom_dict)

    response = TimeseriesResponse(
        parcel_key=parcel_key,
        processing_version=settings.PROCESSING_VERSION,
        series=response_series,
        quality=quality,
        cache=CacheInfo(hit=False, age_seconds=0),
        map_links=map_links,
    )

    cache.set(cache_key, response)

    store.save_timeseries(parcel_key, settings.PROCESSING_VERSION, req.cadence.value, response_series)

    return response
