from __future__ import annotations

from datetime import datetime, timezone
import json
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from pydantic import ValidationError

from ai_bridge.adapters.ventilation.analysis import (
    ANALYSIS_THINK,
    PROMPT_VERSION,
    build_ventilation_prompt,
    summarize_ventilation_window,
)
from ai_bridge.analysis.schemas import VentilationAnalysisResult
from ai_bridge.analysis.service import VentilationAnalysisService, aligned_window
from ai_bridge.ollama.client import (
    OllamaChatResult,
    OllamaClient,
    compact_schema_for_ollama,
)
from ai_bridge.settings import Settings
from ai_bridge.storage.models import TelemetrySampleRecord


def _sample(*, minute: int, supply: float, extract: float) -> TelemetrySampleRecord:
    captured_at = datetime(2026, 8, 10, 12, minute, tzinfo=timezone.utc)
    return TelemetrySampleRecord(
        batch_record_id=1,
        source_id="workshop-ventilation-cm5-01",
        sample_id=f"sample-{minute}",
        sequence=minute + 1,
        captured_at=captured_at,
        received_at=captured_at,
        metrics={
            "mode": "STOP",
            "setpoints": {
                "supply_voltage": supply,
                "extract_voltage": extract,
            },
            "hardware_ready": True,
            "output_state_known": True,
            "consecutive_hardware_failures": 0,
            "active_alarms": [],
            "sensor_bus": None,
        },
    )


def _normal_result(summary: str = "Brak widocznej anomalii w analizowanym oknie.") -> VentilationAnalysisResult:
    return VentilationAnalysisResult(
        status="normal",
        summary=summary,
        confidence=0.7,
        observations=["Sterownik i dane telemetryczne są dostępne do interpretacji."],
        anomalies=[],
        recommendations=[],
        data_quality_notes=["Historyczny baseline nie jest jeszcze dostępny."],
    )


def test_aligned_window_returns_last_completed_quarter_hour() -> None:
    now = datetime(2026, 8, 10, 12, 37, 44, tzinfo=timezone.utc)
    start, end = aligned_window(now, 15)
    assert start == datetime(2026, 8, 10, 12, 15, tzinfo=timezone.utc)
    assert end == datetime(2026, 8, 10, 12, 30, tzinfo=timezone.utc)


def test_settings_reject_window_that_does_not_divide_hour() -> None:
    with pytest.raises(ValidationError):
        Settings(analysis_window_minutes=7)


def test_summary_contains_only_deterministic_math() -> None:
    samples = [
        _sample(minute=0, supply=0.0, extract=1.0),
        _sample(minute=5, supply=5.0, extract=3.0),
        _sample(minute=10, supply=10.0, extract=5.0),
    ]
    summary = summarize_ventilation_window(
        source_id="workshop-ventilation-cm5-01",
        window_start=datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc),
        window_end=datetime(2026, 8, 10, 12, 15, tzinfo=timezone.utc),
        samples=samples,
    )

    assert summary["analysis_context"]["historical_baseline_available"] is False
    assert summary["analysis_context"]["expected_operating_state_known"] is False
    assert summary["window"]["sample_count"] == 3
    assert summary["system"]["mode_counts"] == {"STOP": 3}
    assert summary["system"]["setpoints"]["supply_voltage"]["mean"] == 5.0
    assert summary["system"]["setpoints"]["supply_voltage"]["min"] == 0.0
    assert summary["system"]["setpoints"]["supply_voltage"]["max"] == 10.0
    assert summary["system"]["setpoints"]["supply_voltage"]["slope_per_minute"] == 1.0
    assert summary["system"]["active_alarm_sample_count"] == 0
    assert summary["sensor_bus"]["samples_present"] == 0


def test_prompt_v6_keeps_v5_content_and_enables_thinking_profile() -> None:
    summary = summarize_ventilation_window(
        source_id="workshop-ventilation-cm5-01",
        window_start=datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc),
        window_end=datetime(2026, 8, 10, 12, 15, tzinfo=timezone.utc),
        samples=[_sample(minute=0, supply=0.0, extract=0.0)],
    )
    messages = build_ventilation_prompt(summary)
    system = messages[0]["content"]

    assert PROMPT_VERSION == "ventilation-v6-thinking"
    assert ANALYSIS_THINK is True
    assert "historyczny baseline warsztatu nie jest jeszcze dostępny" in system
    assert "Tryb STOP i setpointy 0 V" in system
    assert "zadanymi sygnałami sterującymi 0-10 V" in system
    assert "PM, VOC, NOx, temperaturę i wilgotność" in system
    assert "provenance" not in system.lower()


def test_analysis_result_validates_only_structure_and_basic_ranges() -> None:
    result = VentilationAnalysisResult(
        status="anomaly",
        summary="Model wykrył zachowanie warte uwagi.",
        confidence=0.8,
        observations=[],
        anomalies=["VOC rośnie w analizowanym oknie."],
        recommendations=[],
    )
    assert result.observations == []
    assert result.anomalies == ["VOC rośnie w analizowanym oknie."]

    with pytest.raises(ValidationError):
        VentilationAnalysisResult(
            status="normal",
            summary="Niepoprawny confidence.",
            confidence=1.5,
        )


def test_compact_schema_is_flat_and_grammar_friendly() -> None:
    schema = VentilationAnalysisResult.model_json_schema()
    compact = compact_schema_for_ollama(schema)
    encoded = json.dumps(compact, sort_keys=True)

    assert '"$defs"' not in encoded
    assert '"$ref"' not in encoded
    assert '"maxLength"' not in encoded
    assert '"maxItems"' not in encoded
    assert compact["properties"]["schema_version"]["enum"] == [1]
    assert compact["properties"]["observations"]["items"]["type"] == "string"
    assert compact["properties"]["anomalies"]["items"]["type"] == "string"
    assert compact["properties"]["recommendations"]["items"]["type"] == "string"


class FakeRepository:
    def __init__(
        self,
        samples: list[TelemetrySampleRecord],
        *,
        existing: Any | None = None,
    ) -> None:
        self.samples = samples
        self.existing = existing
        self.saved: dict[str, Any] | None = None

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


class CapturingOllama:
    def __init__(self) -> None:
        self.kwargs: dict[str, Any] | None = None

    def chat_structured(self, **kwargs):
        self.kwargs = kwargs
        return OllamaChatResult(
            content=_normal_result().model_dump_json(),
            model="qwen3.6:35b",
            prompt_eval_count=123,
            eval_count=45,
            total_duration_ns=999,
        )


def test_service_skips_ollama_when_sample_count_is_below_gate() -> None:
    repository = FakeRepository([_sample(minute=0, supply=0.0, extract=0.0)])
    service = VentilationAnalysisService(
        repository=repository,  # type: ignore[arg-type]
        ollama=ForbiddenOllama(),  # type: ignore[arg-type]
        model="qwen3.6:35b",
        think=ANALYSIS_THINK,
        temperature=0.0,
        min_samples=120,
    )

    result = service.analyze_window(
        source_id="workshop-ventilation-cm5-01",
        window_start=datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc),
        window_end=datetime(2026, 8, 10, 12, 15, tzinfo=timezone.utc),
    )

    assert result.result.status == "insufficient_data"
    assert repository.saved is not None
    assert repository.saved["raw_response"] is None
    assert repository.saved["sample_count"] == 1


def test_service_uses_structured_schema_without_embedding_schema_in_prompt() -> None:
    repository = FakeRepository([_sample(minute=0, supply=0.0, extract=0.0)])
    ollama = CapturingOllama()
    service = VentilationAnalysisService(
        repository=repository,  # type: ignore[arg-type]
        ollama=ollama,  # type: ignore[arg-type]
        model="qwen3.6:35b",
        think=ANALYSIS_THINK,
        temperature=0.0,
        min_samples=1,
    )

    result = service.analyze_window(
        source_id="workshop-ventilation-cm5-01",
        window_start=datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc),
        window_end=datetime(2026, 8, 10, 12, 15, tzinfo=timezone.utc),
    )

    assert result.result.status == "normal"
    assert ollama.kwargs is not None
    assert ollama.kwargs["think"] is True
    sampling_schema = ollama.kwargs["response_schema"]
    assert sampling_schema["properties"]["observations"]["items"]["type"] == "string"
    prompt_text = ollama.kwargs["messages"][-1]["content"]
    assert "Wymagany JSON Schema odpowiedzi" not in prompt_text


def test_service_reuses_existing_analysis_without_calling_ollama() -> None:
    stored_result = _normal_result("Zapisany wynik istniejącej analizy.")
    existing = SimpleNamespace(
        analysis_id="existing-analysis-id",
        sample_count=180,
        result=stored_result.model_dump(mode="json"),
    )
    repository = FakeRepository([], existing=existing)
    service = VentilationAnalysisService(
        repository=repository,  # type: ignore[arg-type]
        ollama=ForbiddenOllama(),  # type: ignore[arg-type]
        model="qwen3.6:35b",
        think=ANALYSIS_THINK,
        temperature=0.0,
        min_samples=120,
    )

    result = service.analyze_window(
        source_id="workshop-ventilation-cm5-01",
        window_start=datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc),
        window_end=datetime(2026, 8, 10, 12, 15, tzinfo=timezone.utc),
    )

    assert result.reused_existing is True
    assert result.analysis_id == "existing-analysis-id"
    assert result.sample_count == 180
    assert result.result.status == "normal"
    assert repository.saved is None


def test_ollama_structured_chat_uses_schema_non_streaming_and_think_true(monkeypatch) -> None:
    captured: dict[str, Any] = {}

    class FakeResponse:
        status_code = 200

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, Any]:
            return {
                "model": "qwen3.6:35b",
                "message": {
                    "role": "assistant",
                    "content": _normal_result().model_dump_json(),
                },
                "done": True,
                "prompt_eval_count": 123,
                "eval_count": 45,
                "total_duration": 999,
            }

        @property
        def text(self) -> str:
            return ""

    def fake_post(url: str, *, json: dict[str, Any], timeout: float):
        captured["url"] = url
        captured["json"] = json
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr(httpx, "post", fake_post)

    client = OllamaClient(base_url="http://127.0.0.1:11434", timeout_seconds=300.0)
    schema = compact_schema_for_ollama(VentilationAnalysisResult.model_json_schema())
    result = client.chat_structured(
        model="qwen3.6:35b",
        messages=[{"role": "user", "content": "test"}],
        response_schema=schema,
        think=ANALYSIS_THINK,
        temperature=0.0,
    )

    assert captured["url"] == "http://127.0.0.1:11434/api/chat"
    assert captured["json"]["stream"] is False
    assert captured["json"]["think"] is True
    assert captured["json"]["format"] == schema
    assert captured["json"]["options"]["temperature"] == 0.0
    assert captured["timeout"] == 300.0
    assert result.model == "qwen3.6:35b"
    assert result.prompt_eval_count == 123
    assert result.eval_count == 45
    assert result.total_duration_ns == 999
