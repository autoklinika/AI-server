from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import logging
from uuid import uuid4

from ai_bridge.adapters.ventilation.analysis import (
    PROMPT_VERSION,
    build_ventilation_prompt,
    summarize_ventilation_window,
)
from ai_bridge.analysis.schemas import VentilationAnalysisResult
from ai_bridge.ollama.client import OllamaClient
from ai_bridge.storage.analysis_repository import VentilationAnalysisRepository


LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class AnalysisRunResult:
    analysis_id: str
    source_id: str
    window_start: datetime
    window_end: datetime
    sample_count: int
    model: str
    prompt_version: str
    result: VentilationAnalysisResult
    reused_existing: bool


def aligned_window(now: datetime, minutes: int) -> tuple[datetime, datetime]:
    if minutes < 1 or 60 % minutes != 0:
        raise ValueError("Window minutes must be a positive divisor of 60")
    if now.tzinfo is None:
        raise ValueError("Window alignment requires a timezone-aware datetime")
    current = now.astimezone(timezone.utc)
    aligned_minute = current.minute - (current.minute % minutes)
    end = current.replace(minute=aligned_minute, second=0, microsecond=0)
    start = end - timedelta(minutes=minutes)
    return start, end


class VentilationAnalysisService:
    def __init__(
        self,
        *,
        repository: VentilationAnalysisRepository,
        ollama: OllamaClient,
        model: str,
        think: bool,
        temperature: float,
        min_samples: int,
    ) -> None:
        self.repository = repository
        self.ollama = ollama
        self.model = model
        self.think = think
        self.temperature = temperature
        self.min_samples = min_samples

    def analyze_window(
        self,
        *,
        source_id: str,
        window_start: datetime,
        window_end: datetime,
    ) -> AnalysisRunResult:
        if window_start.tzinfo is None or window_end.tzinfo is None:
            raise ValueError("Analysis window must use timezone-aware datetimes")
        if window_start >= window_end:
            raise ValueError("Analysis window start must be before end")

        existing = self.repository.get_existing(
            source_id=source_id,
            window_start=window_start,
            window_end=window_end,
            model=self.model,
            prompt_version=PROMPT_VERSION,
        )
        if existing is not None:
            validated = VentilationAnalysisResult.model_validate(existing.result)
            return AnalysisRunResult(
                analysis_id=existing.analysis_id,
                source_id=source_id,
                window_start=window_start,
                window_end=window_end,
                sample_count=existing.sample_count,
                model=self.model,
                prompt_version=PROMPT_VERSION,
                result=validated,
                reused_existing=True,
            )

        samples = self.repository.load_samples(
            source_id=source_id,
            window_start=window_start,
            window_end=window_end,
        )
        summary = summarize_ventilation_window(
            source_id=source_id,
            window_start=window_start,
            window_end=window_end,
            samples=samples,
        )

        if len(samples) < self.min_samples:
            result = VentilationAnalysisResult(
                status="insufficient_data",
                summary=(
                    f"Za mało danych do wiarygodnej analizy okna: "
                    f"{len(samples)} próbek, wymagane minimum {self.min_samples}."
                ),
                confidence=1.0,
                observations=[],
                anomalies=[],
                recommendations=[],
                data_quality_notes=[
                    "Analiza modelu nie została uruchomiona z powodu zbyt małej liczby próbek."
                ],
            )
            chat = None
        else:
            messages = build_ventilation_prompt(summary)
            chat = self.ollama.chat_structured(
                model=self.model,
                messages=messages,
                response_schema=VentilationAnalysisResult.model_json_schema(),
                think=self.think,
                temperature=self.temperature,
            )
            result = VentilationAnalysisResult.model_validate_json(chat.content)

        analysis_id = str(uuid4())
        self.repository.save_analysis(
            analysis_id=analysis_id,
            source_id=source_id,
            window_start=window_start,
            window_end=window_end,
            model=self.model,
            prompt_version=PROMPT_VERSION,
            sample_count=len(samples),
            input_summary=summary,
            result=result.model_dump(mode="json"),
            raw_response=None if chat is None else chat.content,
            prompt_eval_count=None if chat is None else chat.prompt_eval_count,
            eval_count=None if chat is None else chat.eval_count,
            total_duration_ns=None if chat is None else chat.total_duration_ns,
        )
        LOGGER.info(
            "Ventilation analysis stored analysis_id=%s source_id=%s samples=%d window=%s..%s status=%s",
            analysis_id,
            source_id,
            len(samples),
            window_start.isoformat(),
            window_end.isoformat(),
            result.status,
        )
        return AnalysisRunResult(
            analysis_id=analysis_id,
            source_id=source_id,
            window_start=window_start,
            window_end=window_end,
            sample_count=len(samples),
            model=self.model,
            prompt_version=PROMPT_VERSION,
            result=result,
            reused_existing=False,
        )
