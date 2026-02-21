from __future__ import annotations

import datetime

from pydantic import BaseModel, Field, model_validator

from .common import Cadence, GeoJSONGeometry, MetricName

# Sentinel-2 L2A availability starts ~2015-06-23
_S2_EARLIEST = datetime.date(2015, 7, 1)


class FeaturesRequest(BaseModel):
    geometry: GeoJSONGeometry
    date_start: datetime.date
    date_end: datetime.date
    metrics: list[MetricName] = Field(
        default_factory=lambda: [MetricName.ndvi, MetricName.ndwi, MetricName.canopy_proxy]
    )
    cadence: Cadence = Cadence.monthly
    buffers_m: list[int] = Field(default_factory=lambda: [50, 200])
    force_recompute: bool = False

    @model_validator(mode="after")
    def _validate_dates(self):
        if self.date_start >= self.date_end:
            raise ValueError("date_start must be before date_end")
        if self.date_start < _S2_EARLIEST:
            raise ValueError(f"date_start cannot be before {_S2_EARLIEST} (Sentinel-2 availability)")
        if self.date_end > datetime.date.today():
            raise ValueError("date_end cannot be in the future")
        return self


class TimeseriesRequest(BaseModel):
    geometry: GeoJSONGeometry
    date_start: datetime.date
    date_end: datetime.date
    metrics: list[MetricName] = Field(
        default_factory=lambda: [MetricName.ndvi, MetricName.ndwi]
    )
    cadence: Cadence = Cadence.monthly
    max_scenes_per_month: int = Field(default=2, ge=1, le=5)
    force_recompute: bool = False

    @model_validator(mode="after")
    def _validate_dates(self):
        if self.date_start >= self.date_end:
            raise ValueError("date_start must be before date_end")
        if self.date_start < _S2_EARLIEST:
            raise ValueError(f"date_start cannot be before {_S2_EARLIEST} (Sentinel-2 availability)")
        if self.date_end > datetime.date.today():
            raise ValueError("date_end cannot be in the future")
        return self


class ScoreRequest(BaseModel):
    geometry: GeoJSONGeometry
    date_end: datetime.date
    lookback_years: int = Field(default=5, ge=1, le=10)
    force_recompute: bool = False

    @model_validator(mode="after")
    def _validate_dates(self):
        date_start = self.date_end - datetime.timedelta(days=self.lookback_years * 365)
        if date_start < _S2_EARLIEST:
            raise ValueError(
                f"lookback of {self.lookback_years}y from {self.date_end} reaches before {_S2_EARLIEST}"
            )
        if self.date_end > datetime.date.today():
            raise ValueError("date_end cannot be in the future")
        return self
