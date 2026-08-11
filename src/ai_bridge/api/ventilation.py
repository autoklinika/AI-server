from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request

from ai_bridge.adapters.ventilation.schemas import (
    TelemetryBatchAck,
    VentilationTelemetryBatch,
)
from ai_bridge.analysis.schemas import (
    VentilationAnalysisDelivery,
    VentilationAnalysisResult,
)
from ai_bridge.core.errors import UnsupportedSchemaVersion


router = APIRouter(prefix="/api/v1/ventilation", tags=["ventilation"])


def _delivery_timestamp(value: datetime) -> datetime:
    """Keep the delivery contract timezone-aware across PostgreSQL and dev SQLite."""

    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


@router.post("/telemetry/batches", response_model=TelemetryBatchAck)
def ingest_telemetry(
    batch: VentilationTelemetryBatch,
    request: Request,
) -> TelemetryBatchAck:
    if batch.schema_version != 1:
        raise UnsupportedSchemaVersion(batch.schema_version)

    result = request.app.state.ventilation_repository.ingest(batch)
    return TelemetryBatchAck(
        source_id=batch.source_id,
        batch_id=batch.batch_id,
        received=result.received,
        stored=result.stored,
        duplicates=result.duplicates,
        rejected=0,
        server_time=result.received_at,
    )


@router.get("/analysis/latest", response_model=VentilationAnalysisDelivery)
def latest_analysis(
    request: Request,
    source_id: Annotated[str, Query(min_length=1, max_length=128)],
) -> VentilationAnalysisDelivery:
    """Return the newest stored advisory result for one telemetry source.

    This is a read-only delivery endpoint. It does not invoke Ollama/Qwen and it
    cannot issue or accept ventilation control commands.
    """

    record = request.app.state.ventilation_analysis_repository.get_latest(
        source_id=source_id
    )
    if record is None:
        raise HTTPException(status_code=404, detail="analysis_not_found")

    return VentilationAnalysisDelivery(
        analysis_id=record.analysis_id,
        source_id=record.source_id,
        window_start=_delivery_timestamp(record.window_start),
        window_end=_delivery_timestamp(record.window_end),
        created_at=_delivery_timestamp(record.created_at),
        sample_count=record.sample_count,
        model=record.model,
        prompt_version=record.prompt_version,
        result=VentilationAnalysisResult.model_validate(record.result),
    )
