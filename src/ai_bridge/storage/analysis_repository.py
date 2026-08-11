from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select

from .database import Database
from .models import TelemetrySampleRecord, VentilationAnalysisRunRecord


class VentilationAnalysisRepository:
    def __init__(self, database: Database) -> None:
        self._database = database

    def load_samples(
        self,
        *,
        source_id: str,
        window_start: datetime,
        window_end: datetime,
    ) -> list[TelemetrySampleRecord]:
        with self._database.session() as session:
            rows = session.scalars(
                select(TelemetrySampleRecord)
                .where(
                    TelemetrySampleRecord.source_id == source_id,
                    TelemetrySampleRecord.captured_at >= window_start,
                    TelemetrySampleRecord.captured_at < window_end,
                )
                .order_by(TelemetrySampleRecord.captured_at)
            ).all()
            return list(rows)

    def get_existing(
        self,
        *,
        source_id: str,
        window_start: datetime,
        window_end: datetime,
        model: str,
        prompt_version: str,
    ) -> VentilationAnalysisRunRecord | None:
        with self._database.session() as session:
            return session.scalar(
                select(VentilationAnalysisRunRecord).where(
                    VentilationAnalysisRunRecord.source_id == source_id,
                    VentilationAnalysisRunRecord.window_start == window_start,
                    VentilationAnalysisRunRecord.window_end == window_end,
                    VentilationAnalysisRunRecord.model == model,
                    VentilationAnalysisRunRecord.prompt_version == prompt_version,
                )
            )

    def get_latest(self, *, source_id: str) -> VentilationAnalysisRunRecord | None:
        with self._database.session() as session:
            return session.scalar(
                select(VentilationAnalysisRunRecord)
                .where(VentilationAnalysisRunRecord.source_id == source_id)
                .order_by(
                    VentilationAnalysisRunRecord.window_end.desc(),
                    VentilationAnalysisRunRecord.created_at.desc(),
                )
                .limit(1)
            )

    def save_analysis(
        self,
        *,
        analysis_id: str,
        source_id: str,
        window_start: datetime,
        window_end: datetime,
        model: str,
        prompt_version: str,
        sample_count: int,
        input_summary: dict[str, Any],
        result: dict[str, Any],
        raw_response: str | None,
        prompt_eval_count: int | None,
        eval_count: int | None,
        total_duration_ns: int | None,
    ) -> VentilationAnalysisRunRecord:
        record = VentilationAnalysisRunRecord(
            analysis_id=analysis_id,
            source_id=source_id,
            window_start=window_start,
            window_end=window_end,
            model=model,
            prompt_version=prompt_version,
            sample_count=sample_count,
            status=str(result["status"]),
            input_summary=input_summary,
            result=result,
            raw_response=raw_response,
            prompt_eval_count=prompt_eval_count,
            eval_count=eval_count,
            total_duration_ns=total_duration_ns,
        )
        with self._database.session() as session:
            session.add(record)
            session.flush()
        return record
