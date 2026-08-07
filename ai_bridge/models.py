from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class TelemetrySample(BaseModel):
    model_config = ConfigDict(extra="forbid")

    timestamp: datetime
    measurements: dict[str, float | int] = Field(default_factory=dict)
    states: dict[str, Any] = Field(default_factory=dict)

    @field_validator("timestamp")
    @classmethod
    def timestamp_must_be_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamp must include timezone information")
        return value


class TelemetryBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int = Field(ge=1)
    source: str = Field(min_length=1, max_length=64)
    device_id: str = Field(min_length=1, max_length=128)
    batch_id: str = Field(min_length=1, max_length=160)
    sequence: int = Field(ge=0)
    timestamp_start: datetime
    timestamp_end: datetime
    samples: list[TelemetrySample] = Field(min_length=1, max_length=10000)

    @field_validator("timestamp_start", "timestamp_end")
    @classmethod
    def batch_timestamps_must_be_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("batch timestamps must include timezone information")
        return value

    @model_validator(mode="after")
    def validate_time_range(self) -> "TelemetryBatch":
        if self.timestamp_end < self.timestamp_start:
            raise ValueError("timestamp_end must not be earlier than timestamp_start")
        for sample in self.samples:
            if not (self.timestamp_start <= sample.timestamp <= self.timestamp_end):
                raise ValueError("sample timestamp outside batch time range")
        return self


class BatchAck(BaseModel):
    accepted: bool
    duplicate: bool
    batch_id: str
    received_at: datetime
    stored_samples: int
    message: str


class EventIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int = Field(ge=1)
    source: str = Field(min_length=1, max_length=64)
    device_id: str = Field(min_length=1, max_length=128)
    event_id: str = Field(min_length=1, max_length=160)
    timestamp: datetime
    severity: str = Field(pattern="^(info|warning|critical)$")
    event_type: str = Field(min_length=1, max_length=128)
    payload: dict[str, Any] = Field(default_factory=dict)

    @field_validator("timestamp")
    @classmethod
    def event_timestamp_must_be_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamp must include timezone information")
        return value


class EventAck(BaseModel):
    accepted: bool
    duplicate: bool
    event_id: str
    received_at: datetime


class HistoryPoint(BaseModel):
    timestamp: datetime
    source: str
    device_id: str
    metric: str
    value: float


class HistoryResponse(BaseModel):
    metric: str
    points: list[HistoryPoint]


class Recommendation(BaseModel):
    analysis_id: str
    source: str
    created_at: datetime
    summary: str
    confidence: float = Field(ge=0.0, le=1.0)
    details: dict[str, Any] = Field(default_factory=dict)


class RecommendationResponse(BaseModel):
    available: bool
    recommendation: Recommendation | None = None


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str
    database: str
    analysis_enabled: bool
    control_commands_supported: bool = False
