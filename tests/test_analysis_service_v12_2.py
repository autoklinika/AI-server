from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ai_bridge.adapters.ventilation.analysis_v12_2 import (
    ANALYSIS_THINK,
    PROMPT_VERSION,
    EnvironmentalDecisionV122,
)
from ai_bridge.analysis.service_v12_2 import VentilationAnalysisServiceV122
from ai_bridge.ollama.client import OllamaChatResult
from ai_bridge.storage.models import TelemetrySampleRecord


def _sample(*, minute: int = 0) -> TelemetrySampleRecord:
    captured_at = datetime(2026, 8, 19, 10, minute, tzinfo=timezone.utc)
    return TelemetrySampleRecord(
        batch_record_id=1,
        source_id="workshop-ventilation-cm5-01",
        sample_id=f"v12-2-{minute}",
        sequence=minute + 1,
        captured_at=captured_at,
        received_at=captured_at,
        metrics={
            "mode": "MANUAL",
            "setpoints": {
                "supply_voltage": 6.0,
                "extract_voltage": 7.0,
            },
            "hardware_ready": True,
            "output_state_known": True,
            "consecutive_hardware_failures": 0,
            "active_alarms": [],
            "sensor_bus": None,
        },
    )


class FakeRepository:
    def __init__(self, samples: list[TelemetrySampleRecord]) -> None:
        self.samples = samples
        self.saved: dict[str, Any] | None = None
        self.existing = None

    def get_existing(self, **_kwargs):
        return self.existing

    def load_samples(self, **_kwargs):
        return self.samples

    def save_analysis(self, **kwargs):
        self.saved = kwargs
        return None


class ForbiddenOllama:
    def chat_structured(self, **_kwargs):
        raise AssertionError("Ollama must not be called")


class EnvironmentalOllama:
    def __init__(self) -> None:
        self.kwargs: dict[str, Any] | None = None

    def chat_structured(self, **kwargs):
        self.kwargs = kwargs
        content = EnvironmentalDecisionV122(
            environmental_attention=False,
            selected_fact_ids=[],
        ).model_dump_json()
        return OllamaChatResult(
            content=content,
            model="qwen3.6:35b",
            prompt_eval_count=100,
            eval_count=20,
            total_duration_ns=123456,
        )


def _service(repository, ollama, *, min_samples: int) -> VentilationAnalysisServiceV122:
    return VentilationAnalysisServiceV122(
        repository=repository,  # type: ignore[arg-type]
        ollama=ollama,  # type: ignore[arg-type]
        model="qwen3.6:35b",
        think=ANALYSIS_THINK,
        temperature=0.0,
        min_samples=min_samples,
    )


def test_v12_2_service_uses_environmental_decision_schema_and_python_renderer() -> None:
    repository = FakeRepository([_sample()])
    ollama = EnvironmentalOllama()
    service = _service(repository, ollama, min_samples=1)

    result = service.analyze_window(
        source_id="workshop-ventilation-cm5-01",
        window_start=datetime(2026, 8, 19, 10, 0, tzinfo=timezone.utc),
        window_end=datetime(2026, 8, 19, 10, 15, tzinfo=timezone.utc),
    )

    assert result.prompt_version == PROMPT_VERSION
    assert result.result.status == "no_anomaly_detected"
    assert result.result.operator_recommendation_pl == (
        "Na podstawie tego okna nie ma dodatkowych zaleceń."
    )
    assert result.result.operator_view is not None
    assert result.result.operator_view.status_label_pl == "BRAK ANOMALII"
    assert result.result.operator_view.headline_pl == "Brak istotnych zmian"
    assert ollama.kwargs is not None
    assert ollama.kwargs["think"] is False
    assert (
        ollama.kwargs["response_schema"]["properties"]["environmental_attention"]["type"]
        == "boolean"
    )
    assert "analysis_pl" not in ollama.kwargs["response_schema"]["properties"]
    assert repository.saved is not None
    assert repository.saved["prompt_version"] == PROMPT_VERSION
    assert repository.saved["result"]["status"] == "no_anomaly_detected"
    assert repository.saved["result"]["operator_view"]["schema_version"] == 1
    assert "environmental_attention" in repository.saved["raw_response"]


def test_v12_2_service_keeps_sample_gate_without_ollama_call() -> None:
    repository = FakeRepository([_sample()])
    service = _service(repository, ForbiddenOllama(), min_samples=120)

    result = service.analyze_window(
        source_id="workshop-ventilation-cm5-01",
        window_start=datetime(2026, 8, 19, 10, 0, tzinfo=timezone.utc),
        window_end=datetime(2026, 8, 19, 10, 15, tzinfo=timezone.utc),
    )

    assert result.prompt_version == PROMPT_VERSION
    assert result.result.status == "insufficient_data"
    assert result.result.operator_view is not None
    assert result.result.operator_view.status_label_pl == "NIEWYSTARCZAJĄCE DANE"
    assert repository.saved is not None
    assert repository.saved["raw_response"] is None
    assert repository.saved["prompt_version"] == PROMPT_VERSION
    assert repository.saved["result"]["operator_view"]["schema_version"] == 1
