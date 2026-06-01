from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException

from ..auth.dependencies import UserClaims, current_user
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


@router.post("/location/features", response_model=FeaturesResponse)
async def post_features(req: FeaturesRequest, user: UserClaims = Depends(current_user)):
    trace_id = uuid.uuid4().hex[:12]

    ds = req.date_start.isoformat()
    de = req.date_end.isoformat()

    cache_key = (
        f"feat|{req.geometry.model_dump_json()}"
        f"|{ds}|{de}"
        f"|{','.join(m.value for m in req.metrics)}"
        f"|{settings.PROCESSING_VERSION}"
    )

    if not req.force_recompute:
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

    try:
        location_key, features, quality, series = await run_features(
            geom_geojson=req.geometry.model_dump(),
            date_start=ds,
            date_end=de,
            metrics=req.metrics,
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
    # Attribute to the authenticated user; req.customer_id is ignored.
    store.save_geometry(location_key, geom_dict, name=req.name, customer_id=user.user_id)

    map_links = build_map_links(location_key, geom_dict)

    response = FeaturesResponse(
        location_key=location_key,
        processing_version=settings.PROCESSING_VERSION,
        date_window=DateWindow(start=ds, end=de),
        features=features,
        quality=quality,
        cache=CacheInfo(hit=False, age_seconds=0),
        map_links=map_links,
    )

    cache.set(cache_key, response)

    store.save_features(
        location_key, settings.PROCESSING_VERSION,
        ds, de,
        features, quality.model_dump(),
    )
    store.save_timeseries(location_key, settings.PROCESSING_VERSION, "monthly", series)

    return response
