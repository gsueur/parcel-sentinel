from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class MetricName(str, Enum):
    ndvi = "ndvi"
    ndwi = "ndwi"
    canopy_proxy = "canopy_proxy"


class Cadence(str, Enum):
    monthly = "monthly"


class GeoJSONGeometry(BaseModel):
    type: str = Field(..., pattern="^(Polygon|MultiPolygon|Point)$")
    coordinates: list[Any]


class DateWindow(BaseModel):
    start: str
    end: str


class CacheInfo(BaseModel):
    hit: bool
    age_seconds: int


class QualityInfo(BaseModel):
    months_total: int = 0
    months_observed: int = 0
    mean_cloud_fraction: float = 0.0
    flags: list[str] = Field(default_factory=list)


class MapLinks(BaseModel):
    geojson_io_url: str | None = None
    thumbnail_url: str | None = None


class MonthRecord(BaseModel):
    month: str
    mean: float | None = None
    obs: int = 0
    cloud: float = 0.0
