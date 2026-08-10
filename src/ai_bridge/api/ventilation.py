from __future__ import annotations

from fastapi import APIRouter, Request

from ai_bridge.adapters.ventilation.schemas import (
    TelemetryBatchAck,
    VentilationTelemetryBatch,
)
from ai_bridge.core.errors import UnsupportedSchemaVersion


router = APIRouter(prefix="/api/v1/ventilation", tags=["ventilation"])


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
