from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from .config import settings
from .routes import auth, features, health, jobs, locations, report, score, thumbnail, timeseries
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


_404_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>404 — Location Sentinel</title>
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
       background: #f1f5f9; color: #1e293b; font-size: 14px;
       min-height: 100vh; display: flex; flex-direction: column; }
.header { padding: 20px 24px 16px; border-bottom: 1px solid #e2e8f0; background: #fff; }
.header h1 { font-size: 1.1rem; font-weight: 700; color: #0f172a; }
.header small { color: #94a3b8; font-size: 0.78rem; font-family: monospace; }
.container { max-width: 480px; margin: 100px auto; padding: 24px; text-align: center; }
.code { font-size: 5rem; font-weight: 800; color: #e2e8f0; line-height: 1;
        font-family: monospace; letter-spacing: -4px; }
.label { font-size: 1.1rem; font-weight: 600; color: #0f172a; margin: 16px 0 8px; }
.desc { color: #64748b; font-size: 0.9rem; line-height: 1.6; }
footer { margin-top: auto; padding: 16px 24px; border-top: 1px solid #e2e8f0;
         background: #fff; text-align: center; color: #94a3b8; font-size: 0.75rem; }
</style>
</head>
<body>
<div class="header">
  <h1>Location Sentinel Analytics API</h1>
  <small>Climate risk indicators from satellite data</small>
</div>
<div class="container">
  <div class="code">404</div>
  <div class="label">Nothing here.</div>
  <div class="desc">
    This endpoint does not exist or is not publicly accessible.<br>
    If you received this URL from someone, reach out to them directly.
  </div>
</div>
<footer>Location Sentinel &mdash; Geomermaids</footer>
</body>
</html>"""


def _is_browser(request: Request) -> bool:
    ua = request.headers.get("user-agent", "")
    return any(token in ua for token in ("Mozilla", "Chrome", "Safari", "Opera", "Edg"))


def create_app() -> FastAPI:
    app = FastAPI(
        title="Location Sentinel Analytics API",
        version="0.1.0",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException):
        if exc.status_code == 404 and _is_browser(request):
            return HTMLResponse(content=_404_HTML, status_code=404)
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health.router, prefix="/v1")
    app.include_router(auth.router, prefix="/v1")
    app.include_router(timeseries.router, prefix="/v1", include_in_schema=False)
    app.include_router(features.router, prefix="/v1", include_in_schema=False)
    app.include_router(score.router, prefix="/v1", include_in_schema=False)
    app.include_router(thumbnail.router, prefix="/v1", include_in_schema=False)
    app.include_router(report.router, prefix="/v1", include_in_schema=False)
    app.include_router(jobs.router, prefix="/v1", include_in_schema=False)
    app.include_router(locations.router, prefix="/v1")

    return app
