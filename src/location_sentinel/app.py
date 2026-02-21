from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from .config import settings
from .routes import customers, features, health, locations, report, score, thumbnail, timeseries
from .storage.duckdb_store import store


@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.basicConfig(
        level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    store.connect()
    yield
    store.close()


def create_app() -> FastAPI:
    app = FastAPI(
        title="Location Sentinel Analytics API",
        version="0.1.0",
        lifespan=lifespan,
    )

    app.include_router(health.router, prefix="/v1")
    app.include_router(timeseries.router, prefix="/v1")
    app.include_router(features.router, prefix="/v1")
    app.include_router(score.router, prefix="/v1")
    app.include_router(thumbnail.router, prefix="/v1")
    app.include_router(report.router, prefix="/v1")
    app.include_router(locations.router, prefix="/v1")
    app.include_router(customers.router, prefix="/v1")

    return app
