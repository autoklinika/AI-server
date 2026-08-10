from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import logging
from typing import Any
from uuid import uuid4

from ai_bridge.adapters.ventilation.analysis import (
    PROMPT_VERSION,
    build_ventilation_prompt,
    summarize_ventilation_window,
)
from ai_bridge.analysis.schemas import VentilationAnalysisResult
from ai_bridge.ollama.client import OllamaClient, compact_schema_for_ollama
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


def _resolve_summary_path(summary: dict[str, Any], path: str) -> Any:
    current: Any = summary
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            raise ValueError(f"Analysis provenance path does not exist in input_summary: {path}")
        current = current[part]
    return current


def _required_provenance_paths(summary: dict[str, Any]) -> set[str]:
    nodes = summary.get("sensor_bus", {}).get("nodes", {})
    if not isinstance(nodes, dict) or not nodes:
        return set()

    required = {
        "analysis_context.historical_baseline_available",
        "analysis_context.expected_operating_state_known",
        "system.latest_mode",
        "system.setpoints.supply_voltage.mean",
        "system.setpoints.extract_voltage.mean",
        "system.active_alarm_sample_count",
        "sensor_bus.ready_true_ratio",
        "sensor_bus.worker_alive_true_ratio",
    }
    for address in nodes:
        base = f"sensor_bus.nodes.{address}"
        required.update(
            {
                f"{base}.online_true_ratio",
                f"{base}.measurement_valid_true_ratio",
            }
        )
        for field in ("pm2_5_ug_m3", "pm10_0_ug_m3", "voc_index"):
            metric = f"{base}.readings.{field}"
            required.update(
                {
                    f"{metric}.mean",
                    f"{metric}.delta",
                    f"{metric}.slope_per_minute",
                }
            )
        for field in ("temperature_celsius", "humidity_percent"):
            metric = f"{base}.readings.{field}"
            required.update({f"{metric}.mean", f"{metric}.delta"})
    return required


def validate_analysis_provenance(
    summary: dict[str, Any],
    result: VentilationAnalysisResult,
) -> None:
    """Verify that Qwen cites real deterministic input values before DB persistence.

    This is intentionally not anomaly logic. Python only checks provenance: every
    cited path must exist and every copied JSON value must equal input_summary.
    Qwen remains responsible for interpretation.
    """

    required = _required_provenance_paths(summary)
    if not required:
        return

    provided: dict[str, Any] = {}
    for reference in result.provenance:
        actual = _resolve_summary_path(summary, reference.path)
        try:
            claimed = json.loads(reference.value_json)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"Analysis provenance value_json is not valid JSON for {reference.path}: "
                f"{reference.value_json!r}"
            ) from exc
        if claimed != actual:
            raise ValueError(
                "Analysis provenance value does not match input_summary for "
                f"{reference.path}: claimed={claimed!r} actual={actual!r}"
            )
        provided[reference.path] = actual

    missing = sorted(required - provided.keys())
    if missing:
        raise ValueError(
            "Analysis provenance is incomplete; missing required input_summary paths: "
            + ", ".join(missing)
        )

    def validate_paths(label: str, paths: list[str]) -> None:
        if not paths:
            raise ValueError(f"{label} must reference at least one provenance path")
        unknown = sorted(set(paths) - provided.keys())
        if unknown:
            raise ValueError(
                f"{label} references paths not present in validated provenance: "
                + ", ".join(unknown)
            )

    for index, observation in enumerate(result.observations):
        validate_paths(f"observation[{index}]", observation.provenance_paths)
    for index, anomaly in enumerate(result.anomalies):
        validate_paths(f"anomaly[{index}]", anomaly.provenance_paths)
    for index, recommendation in enumerate(result.recommendations):
        validate_paths(f"recommendation[{index}]", recommendation.provenance_paths)

    observation_paths = {
        path
        for observation in result.observations
        for path in observation.provenance_paths
    }
    nodes = summary["sensor_bus"]["nodes"]
    for address in nodes:
        pm_delta = f"sensor_bus.nodes.{address}.readings.pm2_5_ug_m3.delta"
        voc_delta = f"sensor_bus.nodes.{address}.readings.voc_index.delta"
        if pm_delta not in observation_paths or voc_delta not in observation_paths:
            raise ValueError(
                "Observations must explicitly reference PM2.5 and VOC delta for every "
                f"sensor node; missing coverage for slave_address={address}"
            )


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
            stored_summary = getattr(existing, "input_summary", None)
            if isinstance(stored_summary, dict):
                validate_analysis_provenance(stored_summary, validated)
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
            validation_schema = VentilationAnalysisResult.model_json_schema()
            sampling_schema = compact_schema_for_ollama(validation_schema)
            messages = build_ventilation_prompt(summary)
            messages[-1]["content"] += (
                "\n\nWymagany JSON Schema odpowiedzi (używany również przez sampler Ollamy):\n"
                + json.dumps(sampling_schema, ensure_ascii=False, sort_keys=True)
            )
            chat = self.ollama.chat_structured(
                model=self.model,
                messages=messages,
                response_schema=sampling_schema,
                think=self.think,
                temperature=self.temperature,
            )
            # The grammar schema is intentionally compact. The complete Pydantic
            # model remains the authoritative post-generation validation boundary.
            result = VentilationAnalysisResult.model_validate_json(chat.content)
            validate_analysis_provenance(summary, result)

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
