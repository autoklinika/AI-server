from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json

from sqlalchemy import select

from ai_bridge.adapters.ventilation.schemas import VentilationTelemetryBatch
from ai_bridge.core.errors import BatchIdentityConflict

from .database import Database
from .models import TelemetryBatchRecord, TelemetrySampleRecord


@dataclass(frozen=True)
class IngestResult:
    received: int
    stored: int
    duplicates: int
    received_at: datetime


class VentilationTelemetryRepository:
    def __init__(self, database: Database) -> None:
        self._database = database

    def ingest(self, batch: VentilationTelemetryBatch) -> IngestResult:
        received_at = datetime.now(timezone.utc)
        payload_hash = self._payload_hash(batch)

        with self._database.session() as session:
            existing_batch = session.scalar(
                select(TelemetryBatchRecord).where(
                    TelemetryBatchRecord.source_id == batch.source_id,
                    TelemetryBatchRecord.batch_id == batch.batch_id,
                )
            )
            if existing_batch is not None:
                if existing_batch.payload_hash != payload_hash:
                    raise BatchIdentityConflict(
                        "source_id/batch_id already exists with different payload"
                    )
                return IngestResult(
                    received=len(batch.samples),
                    stored=0,
                    duplicates=len(batch.samples),
                    received_at=received_at,
                )

            batch_record = TelemetryBatchRecord(
                schema_version=batch.schema_version,
                source_id=batch.source_id,
                batch_id=batch.batch_id,
                created_at=batch.created_at,
                received_at=received_at,
                sample_count=len(batch.samples),
                payload_hash=payload_hash,
            )
            session.add(batch_record)
            session.flush()

            existing_sample_ids = set(
                session.scalars(
                    select(TelemetrySampleRecord.sample_id).where(
                        TelemetrySampleRecord.source_id == batch.source_id,
                        TelemetrySampleRecord.sample_id.in_(
                            [sample.sample_id for sample in batch.samples]
                        ),
                    )
                ).all()
            )

            stored = 0
            for sample in batch.samples:
                if sample.sample_id in existing_sample_ids:
                    continue
                session.add(
                    TelemetrySampleRecord(
                        batch_record_id=batch_record.id,
                        source_id=batch.source_id,
                        sample_id=sample.sample_id,
                        sequence=sample.sequence,
                        captured_at=sample.captured_at,
                        received_at=received_at,
                        metrics=sample.metrics.model_dump(mode="json"),
                    )
                )
                stored += 1

            return IngestResult(
                received=len(batch.samples),
                stored=stored,
                duplicates=len(batch.samples) - stored,
                received_at=received_at,
            )

    @staticmethod
    def _payload_hash(batch: VentilationTelemetryBatch) -> str:
        canonical = json.dumps(
            batch.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        return sha256(canonical.encode("utf-8")).hexdigest()
