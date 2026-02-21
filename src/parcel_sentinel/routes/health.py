from __future__ import annotations

from fastapi import APIRouter

from ..config import settings
from ..models.responses import HealthResponse
from ..storage.duckdb_store import store

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def health():
    db_ok = store.health_check()
    return HealthResponse(
        status="ok" if db_ok else "degraded",
        version=settings.PROCESSING_VERSION,
        db_ok=db_ok,
    )
