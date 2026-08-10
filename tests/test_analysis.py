from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from pydantic import ValidationError

from ai_bridge.adapters.ventilation.analysis import summarize_ventilation_window
from ai_bridge.analysis.schemas import VentilationAnalysisResult
from ai_bridge.analysis.service import VentilationAnalysisService, aligned_window
from ai_bridge.ollama.client import OllamaClient
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

    assert summary["window"]["sample_count"] == 3
    assert summary["system"]["mode_counts"] == {"STOP": 3}
    assert summary["system"]["setpoints"]["supply_voltage"]["mean"] == 5.0
    assert summary["system"]["setpoints"]["supply_voltage"]["min"] == 0.0
    assert summary["system"]["setpoints"]["supply_voltage"]["max"] == 10.0
    assert summary["system"]["setpoints"]["supply_voltage"]["slope_per_minute"] == 1.0
    assert summary["system"]["active_alarm_sample_count"] == 0
    assert summary["sensor_bus"]["samples_present"] == 0


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


def test_service_skips_ollama_when_sample_count_is_below_gate() -> None:
    repository = FakeRepository([_sample(minute=0, supply=0.0, extract=0.0)])
    service = VentilationAnalysisService(
        repository=repository,  # type: ignore[arg-type]
        ollama=ForbiddenOllama(),  # type: ignore[arg-type]
        model="qwen3.6:35b",
        think=False,
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


def test_service_reuses_existing_analysis_without_calling_ollama() -> None:
    stored_result = VentilationAnalysisResult(
        status="normal",
        summary="Zapisany wynik istniejącej analizy.",
        confidence=0.9,
    )
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
        think=False,
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


def test_ollama_structured_chat_uses_schema_non_streaming_and_think_false(monkeypatch) -> None:
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
                    "content": VentilationAnalysisResult(
                        status="normal",
                        summary="Brak wykrytych anomalii w dostarczonym oknie.",
                        confidence=0.8,
                    ).model_dump_json(),
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
    schema = VentilationAnalysisResult.model_json_schema()
    result = client.chat_structured(
        model="qwen3.6:35b",
        messages=[{"role": "user", "content": "test"}],
        response_schema=schema,
        think=False,
        temperature=0.0,
    )

    assert captured["url"] == "http://127.0.0.1:11434/api/chat"
    assert captured["json"]["stream"] is False
    assert captured["json"]["think"] is False
    assert captured["json"]["format"] == schema
    assert captured["json"]["options"]["temperature"] == 0.0
    assert captured["timeout"] == 300.0
    assert result.model == "qwen3.6:35b"
    assert result.prompt_eval_count == 123
    assert result.eval_count == 45
    assert result.total_duration_ns == 999
