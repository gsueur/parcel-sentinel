from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, HTTPException

from ..config import settings
from ..geometry.validate import GeometryValidationError
from ..models.requests import ScoreRequest
from ..models.responses import ScoreExplanation, ScoreFactor, ScoreResponse
from ..pipeline.score_pipeline import run_score
from ..storage.cache import cache
from ..thumbnails.links import build_map_links

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/parcel/score", response_model=ScoreResponse)
async def post_score(req: ScoreRequest):
    trace_id = uuid.uuid4().hex[:12]

    de = req.date_end.isoformat()

    cache_key = (
        f"score|{req.geometry.model_dump_json()}"
        f"|{de}|{req.lookback_years}"
        f"|{settings.SCORE_VERSION}"
    )

    if not req.force_recompute:
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

    try:
        parcel_key, score_result = await run_score(
            geom_geojson=req.geometry.model_dump(),
            date_end=de,
            lookback_years=req.lookback_years,
        )
    except GeometryValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Computation failed trace_id=%s", trace_id)
        raise HTTPException(status_code=500, detail=f"Computation failed (trace_id={trace_id})")

    scores_dict = {
        "drought_score": score_result.drought_score,
        "wetness_score": score_result.wetness_score,
        "fire_exposure_score": score_result.fire_exposure_score,
        "heat_mitigation_score": score_result.heat_mitigation_score,
        "composite_score": score_result.composite_score,
    }

    explain = ScoreExplanation(
        top_factors=[
            ScoreFactor(name=f["name"], direction=f["direction"], weight=f["weight"])
            for f in score_result.top_factors
        ]
    )

    geom_dict = req.geometry.model_dump()

    from ..storage.duckdb_store import store
    store.save_geometry(parcel_key, geom_dict, name=req.name, customer_id=req.customer_id)

    map_links = build_map_links(parcel_key, geom_dict)

    response = ScoreResponse(
        parcel_key=parcel_key,
        score_version=settings.SCORE_VERSION,
        scores=scores_dict,
        explain=explain,
        map_links=map_links,
    )

    cache.set(cache_key, response)

    store.save_scores(
        parcel_key, settings.SCORE_VERSION,
        req.lookback_years, scores_dict,
    )

    return response
