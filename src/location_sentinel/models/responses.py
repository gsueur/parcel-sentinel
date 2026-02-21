from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from .common import CacheInfo, DateWindow, MapLinks, MonthRecord, QualityInfo


class FeaturesResponse(BaseModel):
    location_key: str
    processing_version: str
    date_window: DateWindow
    features: dict[str, float | None]
    quality: QualityInfo
    cache: CacheInfo
    map_links: MapLinks | None = None


class TimeseriesResponse(BaseModel):
    location_key: str
    processing_version: str
    series: dict[str, list[MonthRecord]]
    quality: QualityInfo
    cache: CacheInfo
    map_links: MapLinks | None = None


class ScoreFactor(BaseModel):
    name: str
    direction: str
    weight: float


class ScoreExplanation(BaseModel):
    top_factors: list[ScoreFactor] = Field(default_factory=list)


class ScoreResponse(BaseModel):
    location_key: str
    score_version: str
    scores: dict[str, int]
    explain: ScoreExplanation
    map_links: MapLinks | None = None


class HealthResponse(BaseModel):
    status: str = "ok"
    version: str = ""
    db_ok: bool = True


class ErrorDetail(BaseModel):
    detail: str
    trace_id: str | None = None
