from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from ..config import settings
from ..storage.cache import cache
from ..storage.duckdb_store import store
from ..thumbnails.static_map import render_location_thumbnail

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/thumbnail/{location_key}.png")
async def get_thumbnail(location_key: str):
    cache_key = f"thumb:{location_key}"
    cached_png = cache.get(cache_key)
    if cached_png is not None:
        return Response(
            content=cached_png,
            media_type="image/png",
            headers={"Cache-Control": "no-cache"},
        )

    geojson = store.get_geometry(location_key)
    if geojson is None:
        raise HTTPException(status_code=404, detail="Location geometry not found")

    try:
        png_bytes = await render_location_thumbnail(geojson)
    except Exception:
        logger.exception("Thumbnail render failed for %s", location_key)
        raise HTTPException(status_code=500, detail="Thumbnail render failed")

    cache.set(cache_key, png_bytes, ttl=settings.THUMBNAIL_CACHE_TTL)

    return Response(
        content=png_bytes,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=86400"},
    )
