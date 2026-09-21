from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ai_bridge.adapters.ventilation.analysis_v12_2 import (
    ANALYSIS_THINK,
    PROMPT_VERSION,
    EnvironmentalDecisionV122,
)
from ai_bridge.analysis.service_v12_2 import VentilationAnalysisServiceV122
from ai_bridge.providers.contracts import (
    LLMExecution,
    LLMRequest,
    LLMResponse,
    LLMUsage,
)
from ai_bridge.storage.models import TelemetrySampleRecord


def _sample(*, minute: int = 0, active_alarm: bool = False) -> TelemetrySampleRecord:
    captured_at = datetime(2026, 8, 19, 10, minute, tzinfo=timezone.utc)
    alarms = []
    if active_alarm:
        alarms = [
            {
                "code": "AERO_BUS_UNAVAILABLE",
                "severity": "critical",
                "message": "Rekuperator AERO niedostępny",
                "active_since": captured_at.isoformat(),
                "last_error": "timeout",
                "occurrences": 1,
                "alert_id": 42,
                "source": "aero",
                "acknowledged": False,
                "acknowledged_at": None,
                "alert_v2": {"weight": 4},
            }
        ]
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
            "active_alarms": alarms,
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


class ForbiddenLLM:
    def generate(self, _request: LLMRequest) -> LLMResponse:
        raise AssertionError("LLM provider must not be called")


class EnvironmentalLLM:
    def __init__(self) -> None:
        self.request: LLMRequest | None = None

    def generate(self, request: LLMRequest) -> LLMResponse:
        self.request = request
        content = EnvironmentalDecisionV122(
            environmental_attention=False,
            selected_fact_ids=[],
        ).model_dump_json()
        return LLMResponse(
            request_id=request.request_id,
            content=content,
            usage=LLMUsage(input_tokens=100, output_tokens=20),
            execution=LLMExecution(
                provider="test-llm",
                model="qwen3.6:35b",
                duration_ns=123456,
            ),
        )


def _service(repository, llm, *, min_samples: int) -> VentilationAnalysisServiceV122:
    return VentilationAnalysisServiceV122(
        repository=repository,  # type: ignore[arg-type]
        llm=llm,  # type: ignore[arg-type]
        model="qwen3.6:35b",
        think=ANALYSIS_THINK,
        temperature=0.0,
        min_samples=min_samples,
    )


def test_v12_2_service_uses_environmental_decision_schema_and_python_renderer() -> None:
    repository = FakeRepository([_sample()])
    llm = EnvironmentalLLM()
    service = _service(repository, llm, min_samples=1)

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
    assert result.result.operator_view.headline_pl == "Brak zmian wymagających uwagi"
    assert llm.request is not None
    assert llm.request.reasoning_enabled is False
    assert llm.request.response_schema is not None
    assert (
        llm.request.response_schema["properties"]["environmental_attention"]["type"]
        == "boolean"
    )
    assert "analysis_pl" not in llm.request.response_schema["properties"]
    assert repository.saved is not None
    assert repository.saved["prompt_version"] == PROMPT_VERSION
    assert repository.saved["result"]["status"] == "no_anomaly_detected"
    assert repository.saved["result"]["operator_view"]["schema_version"] == 1
    assert "environmental_attention" in repository.saved["raw_response"]


def test_v12_2_service_does_not_prioritize_or_render_active_alerts() -> None:
    repository = FakeRepository([_sample(active_alarm=True)])
    llm = EnvironmentalLLM()
    service = _service(repository, llm, min_samples=1)

    result = service.analyze_window(
        source_id="workshop-ventilation-cm5-01",
        window_start=datetime(2026, 8, 19, 10, 0, tzinfo=timezone.utc),
        window_end=datetime(2026, 8, 19, 10, 15, tzinfo=timezone.utc),
    )

    # Audit storage keeps the authoritative source summary, including alarms.
    assert repository.saved is not None
    assert repository.saved["input_summary"]["system"]["active_alarm_sample_count"] == 1
    assert repository.saved["input_summary"]["system"]["active_alarm_codes"] == [
        "AERO_BUS_UNAVAILABLE"
    ]

    # Advisory output and model input are intentionally alert-blind.
    assert result.result.status == "no_anomaly_detected"
    serialized_result = str(repository.saved["result"])
    assert "AERO_BUS_UNAVAILABLE" not in serialized_result
    assert "Aktywny alarm" not in serialized_result
    assert "alarmów CM5" not in serialized_result
    assert llm.request is not None
    serialized_messages = str(llm.request.messages)
    assert "AERO_BUS_UNAVAILABLE" not in serialized_messages
    assert "active_alarm_codes" not in serialized_messages
    assert "active_alarm_sample_count" not in serialized_messages


def test_v12_2_service_keeps_sample_gate_without_llm_call() -> None:
    repository = FakeRepository([_sample()])
    service = _service(repository, ForbiddenLLM(), min_samples=120)

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
