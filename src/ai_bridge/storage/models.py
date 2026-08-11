from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class TelemetryBatchRecord(Base):
    __tablename__ = "ventilation_ingest_batches"
    __table_args__ = (
        UniqueConstraint("source_id", "batch_id", name="uq_vent_batch_source_batch"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False)
    source_id: Mapped[str] = mapped_column(String(128), nullable=False)
    batch_id: Mapped[str] = mapped_column(String(160), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    sample_count: Mapped[int] = mapped_column(Integer, nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)


class TelemetrySampleRecord(Base):
    __tablename__ = "ventilation_telemetry_raw"
    __table_args__ = (
        UniqueConstraint("source_id", "sample_id", name="uq_vent_sample_source_sample"),
        Index("ix_vent_raw_source_captured", "source_id", "captured_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    batch_record_id: Mapped[int] = mapped_column(
        ForeignKey("ventilation_ingest_batches.id", ondelete="CASCADE"),
        nullable=False,
    )
    source_id: Mapped[str] = mapped_column(String(128), nullable=False)
    sample_id: Mapped[str] = mapped_column(String(160), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    metrics: Mapped[dict] = mapped_column(JSON, nullable=False)


class VentilationAnalysisRunRecord(Base):
    __tablename__ = "ventilation_analysis_runs"
    __table_args__ = (
        UniqueConstraint(
            "source_id",
            "window_start",
            "window_end",
            "model",
            "prompt_version",
            name="uq_vent_analysis_window_model_prompt",
        ),
        Index(
            "ix_vent_analysis_source_window_end",
            "source_id",
            "window_end",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    analysis_id: Mapped[str] = mapped_column(String(36), nullable=False, unique=True)
    source_id: Mapped[str] = mapped_column(String(128), nullable=False)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(64), nullable=False)
    sample_count: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    input_summary: Mapped[dict] = mapped_column(JSON, nullable=False)
    result: Mapped[dict] = mapped_column(JSON, nullable=False)
    raw_response: Mapped[str | None] = mapped_column(Text, nullable=True)
    prompt_eval_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    eval_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_duration_ns: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
