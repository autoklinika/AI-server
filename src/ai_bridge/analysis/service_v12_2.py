from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import logging
from uuid import uuid4

from ai_bridge.adapters.ventilation.analysis import summarize_ventilation_window
from ai_bridge.adapters.ventilation.analysis_profile import build_compact_analysis_packet
from ai_bridge.adapters.ventilation.analysis_v12 import build_fact_catalog
from ai_bridge.adapters.ventilation.analysis_v12_2 import (
    PROMPT_VERSION,
    EnvironmentalDecisionV122,
    build_environment_prompt_from_compact,
    render_result,
    resolve_final_decision,
    strip_alert_context,
)
from ai_bridge.analysis.operator_view import (
    render_insufficient_operator_view,
    render_operator_view,
)
from ai_bridge.analysis.schemas import VentilationAnalysisResult
from ai_bridge.ollama.client import OllamaClient, compact_schema_for_ollama
from ai_bridge.storage.analysis_repository import VentilationAnalysisRepository


LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class AnalysisRunResultV122:
    analysis_id: str
    source_id: str
    window_start: datetime
    window_end: datetime
    sample_count: int
    model: str
    prompt_version: str
    result: VentilationAnalysisResult
    reused_existing: bool


class VentilationAnalysisServiceV122:
    """Production service for the grounded v12.2 ventilation analysis profile.

    Qwen receives only the environmental decision packet and returns a tiny
    structured environmental decision. Operator alerts are explicitly excluded
    from advisory input and deterministic result priority; the Alerts tab remains
    the only operator-facing alert authority. Technical telemetry, data-quality
    floors, recommendation text and numerical prose remain deterministic.
    """

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
    ) -> AnalysisRunResultV122:
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
            return AnalysisRunResultV122(
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
                analysis_pl=(
                    f"Za mało danych do wiarygodnej analizy okna: "
                    f"{len(samples)} próbek, wymagane minimum {self.min_samples}."
                ),
                operator_recommendation_pl=(
                    "Poczekać na pełniejsze okno telemetryczne przed oceną zachowania systemu."
                ),
                data_quality_pl=(
                    "Model AI nie został uruchomiony, ponieważ liczba próbek nie spełniła "
                    "minimalnego warunku jakości danych."
                ),
                operator_view=render_insufficient_operator_view(
                    sample_count=len(samples),
                    min_samples=self.min_samples,
                ),
            )
            chat = None
        else:
            # The full deterministic summary is retained for audit/history, but
            # alert lifecycle state is intentionally removed from advisory input
            # and from the deterministic advisory decision/rendering path.
            compact = strip_alert_context(build_compact_analysis_packet(summary))
            sampling_schema = compact_schema_for_ollama(
                EnvironmentalDecisionV122.model_json_schema()
            )
            chat = self.ollama.chat_structured(
                model=self.model,
                messages=build_environment_prompt_from_compact(compact),
                response_schema=sampling_schema,
                think=self.think,
                temperature=self.temperature,
            )
            environmental = EnvironmentalDecisionV122.model_validate_json(chat.content)
            decision = resolve_final_decision(compact, environmental)
            result = render_result(compact, environmental).model_copy(
                update={
                    "operator_view": render_operator_view(
                        compact,
                        decision,
                        build_fact_catalog(compact),
                    )
                }
            )

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
            # For v12.2 raw_response is intentionally the small environmental
            # decision JSON, not operator-facing prose.
            raw_response=None if chat is None else chat.content,
            prompt_eval_count=None if chat is None else chat.prompt_eval_count,
            eval_count=None if chat is None else chat.eval_count,
            total_duration_ns=None if chat is None else chat.total_duration_ns,
        )
        LOGGER.info(
            "Ventilation v12.2 analysis stored analysis_id=%s source_id=%s samples=%d window=%s..%s status=%s",
            analysis_id,
            source_id,
            len(samples),
            window_start.isoformat(),
            window_end.isoformat(),
            result.status,
        )
        return AnalysisRunResultV122(
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
