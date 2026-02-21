from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, HTTPException

from ..config import settings
from ..geometry.validate import GeometryValidationError
from ..models.common import CacheInfo, DateWindow
from ..models.requests import FeaturesRequest
from ..models.responses import FeaturesResponse
from ..pipeline.features_pipeline import run_features
from ..storage.cache import cache
from ..thumbnails.links import build_map_links

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/parcel/features", response_model=FeaturesResponse)
async def post_features(req: FeaturesRequest):
    trace_id = uuid.uuid4().hex[:12]

    ds = req.date_start.isoformat()
    de = req.date_end.isoformat()

    cache_key = (
        f"feat|{req.geometry.model_dump_json()}"
        f"|{ds}|{de}"
        f"|{','.join(m.value for m in req.metrics)}"
        f"|{','.join(str(b) for b in req.buffers_m)}"
        f"|{settings.PROCESSING_VERSION}"
    )

    if not req.force_recompute:
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

    try:
        parcel_key, features, quality = await run_features(
            geom_geojson=req.geometry.model_dump(),
            date_start=ds,
            date_end=de,
            metrics=req.metrics,
            buffers_m=req.buffers_m,
        )
    except GeometryValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Computation failed trace_id=%s", trace_id)
        raise HTTPException(status_code=500, detail=f"Computation failed (trace_id={trace_id})")

    geom_dict = req.geometry.model_dump()

    from ..storage.duckdb_store import store
    store.save_geometry(parcel_key, geom_dict, name=req.name)

    map_links = build_map_links(parcel_key, geom_dict)

    response = FeaturesResponse(
        parcel_key=parcel_key,
        processing_version=settings.PROCESSING_VERSION,
        date_window=DateWindow(start=ds, end=de),
        features=features,
        quality=quality,
        cache=CacheInfo(hit=False, age_seconds=0),
        map_links=map_links,
    )

    cache.set(cache_key, response)

    store.save_features(
        parcel_key, settings.PROCESSING_VERSION,
        ds, de,
        features, quality.model_dump(),
    )

    return response
