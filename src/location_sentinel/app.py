from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .routes import customers, features, health, jobs, locations, report, score, thumbnail, timeseries
from .stac.noaa_tides_client import fetch_tidal_stations
from .storage.duckdb_store import store

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.basicConfig(
        level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    store.connect()
    if store.needs_tidal_station_refresh(settings.NOAA_STATION_REFRESH_DAYS):
        try:
            stations = await fetch_tidal_stations()
            store.store_tidal_stations(stations)
            logger.info("Loaded %d NOAA tidal stations", len(stations))
        except Exception as exc:
            logger.warning("Could not refresh NOAA tidal stations: %s", exc)
    yield
    store.close()


def create_app() -> FastAPI:
    app = FastAPI(
        title="Location Sentinel Analytics API",
        version="0.1.0",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health.router, prefix="/v1")
    app.include_router(timeseries.router, prefix="/v1", include_in_schema=False)
    app.include_router(features.router, prefix="/v1", include_in_schema=False)
    app.include_router(score.router, prefix="/v1", include_in_schema=False)
    app.include_router(thumbnail.router, prefix="/v1", include_in_schema=False)
    app.include_router(report.router, prefix="/v1", include_in_schema=False)
    app.include_router(jobs.router, prefix="/v1", include_in_schema=False)
    app.include_router(locations.router, prefix="/v1")
    app.include_router(customers.router, prefix="/v1")

    return app
