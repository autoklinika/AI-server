from __future__ import annotations

from datetime import datetime, timezone
import json
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from pydantic import ValidationError

from ai_bridge.adapters.ventilation.analysis import (
    _counter_summary,
    summarize_ventilation_window,
)
from ai_bridge.adapters.ventilation.analysis_profile import (
    ANALYSIS_THINK,
    PROMPT_VERSION,
    build_compact_analysis_packet,
    build_ventilation_prompt,
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


def _report_result(
    analysis: str = "W analizowanym oknie nie widać podstaw do zgłoszenia anomalii."
) -> VentilationAnalysisResult:
    return VentilationAnalysisResult(
        status="no_anomaly_detected",
        analysis_pl=analysis,
        operator_recommendation_pl="Kontynuować obserwację kolejnych okien telemetrycznych.",
        data_quality_pl="Dane wystarczające do analizy bieżącego okna; brak baseline'u historycznego.",
    )


def _compact_packet_source_summary() -> dict[str, Any]:
    def metric(
        *,
        mean: float,
        minimum: float,
        maximum: float,
        delta: float,
        slope: float,
    ) -> dict[str, Any]:
        return {
            "count": 179,
            "missing": 0,
            "mean": mean,
            "min": minimum,
            "max": maximum,
            "stddev": 0.5,
            "first": mean - delta,
            "last": mean,
            "delta": delta,
            "slope_per_minute": slope,
        }

    readings = {
        "pm1_0_ug_m3": metric(mean=6.6, minimum=5.6, maximum=8.4, delta=-1.9, slope=-0.12),
        "pm2_5_ug_m3": metric(mean=6.9, minimum=5.8, maximum=8.8, delta=-2.0, slope=-0.13),
        "pm4_0_ug_m3": metric(mean=6.9, minimum=5.8, maximum=8.8, delta=-2.0, slope=-0.13),
        "pm10_0_ug_m3": metric(mean=6.9, minimum=5.8, maximum=8.8, delta=-2.0, slope=-0.13),
        "humidity_percent": metric(mean=42.1, minimum=41.5, maximum=42.9, delta=0.25, slope=-0.01),
        "temperature_celsius": metric(mean=25.1, minimum=25.0, maximum=25.2, delta=0.18, slope=0.01),
        "voc_index": metric(mean=21.1, minimum=10.0, maximum=34.0, delta=16.0, slope=0.99),
        "nox_index": metric(mean=1.0, minimum=1.0, maximum=1.0, delta=0.0, slope=0.0),
    }
    counters = {
        field: {"first": 0, "last": 0, "delta": 0, "max": 0}
        for field in (
            "sensor_errors",
            "modbus_service_errors",
            "communication_errors",
            "consecutive_failures",
            "invalid_measurements",
            "stale_measurements",
            "map_version_errors",
        )
    }
    node = {
        "samples_present": 179,
        "online_true_ratio": 1.0,
        "usable_true_ratio": 1.0,
        "measurement_valid_true_ratio": 1.0,
        "measurement_stale_true_ratio": 0.0,
        "sensor_present_true_ratio": 1.0,
        "readings": readings,
        "counters": counters,
        "latest": {"last_error": None},
    }
    return {
        "schema_version": 1,
        "source_id": "workshop-ventilation-cm5-01",
        "analysis_context": {
            "historical_baseline_available": False,
            "expected_operating_state_known": False,
        },
        "window": {
            "start": "2026-08-10T12:00:00+00:00",
            "end": "2026-08-10T12:15:00+00:00",
            "sample_count": 179,
            "capture_span_seconds": 895.0,
        },
        "system": {
            "mode_counts": {"STOP": 179},
            "latest_mode": "STOP",
            "setpoints": {
                "supply_voltage": metric(mean=0.0, minimum=0.0, maximum=0.0, delta=0.0, slope=0.0),
                "extract_voltage": metric(mean=0.0, minimum=0.0, maximum=0.0, delta=0.0, slope=0.0),
            },
            "hardware_ready_true_ratio": 1.0,
            "output_state_known_true_ratio": 1.0,
            "consecutive_hardware_failures_max": 0,
            "active_alarm_sample_count": 0,
            "active_alarm_codes": [],
        },
        "sensor_bus": {
            "ready_true_ratio": 1.0,
            "worker_alive_true_ratio": 1.0,
            "worker_restarts_max": 0,
            "latest_error": None,
            "nodes": {"1": node, "2": node},
        },
    }


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


def test_cumulative_counter_summary_is_reset_aware() -> None:
    summary = _counter_summary(
        [34, 40, 51, 0, 0, 2],
        cumulative=True,
    )

    assert summary["first"] == 34
    assert summary["last"] == 2
    assert summary["delta"] == 19
    assert summary["max"] == 51

    # Zdarzenia nie mogą zniknąć tylko dlatego,
    # że licznik wrócił do tej samej wartości.
    assert _counter_summary(
        [0, 16, 0],
        cumulative=True,
    )["delta"] == 16


def test_gauge_counter_summary_keeps_signed_state_change() -> None:
    summary = _counter_summary(
        [3, 2, 0],
        cumulative=False,
    )

    assert summary["first"] == 3
    assert summary["last"] == 0
    assert summary["delta"] == -3
    assert summary["max"] == 3


def test_v11_3_compact_packet_keeps_measurements_and_removes_noise() -> None:
    packet = build_compact_analysis_packet(_compact_packet_source_summary())

    assert PROMPT_VERSION == "ventilation-v11.3-semantic-hardening"
    assert ANALYSIS_THINK is False
    assert "humidity_percent" in packet["measurement_capabilities"]["present_in_packet"]
    assert packet["measurement_capabilities"]["not_provided_by_system"] == [
        "co2",
        "fan_rpm",
        "airflow",
    ]
    humidity = packet["sensor_bus"]["nodes"]["1"]["readings"]["humidity_percent"]
    assert humidity["count"] == 179
    assert humidity["missing"] == 0
    assert humidity["mean"] == 42.1
    assert "stddev" not in humidity
    assert "first" not in humidity
    assert "last" not in humidity
    assert packet["sensor_bus"]["nodes"]["1"]["readings"]["voc_index"]["delta"] == 16.0


def test_prompt_v11_3_freezes_semantic_hardening_rules() -> None:
    messages = build_ventilation_prompt(_compact_packet_source_summary())
    system = messages[0]["content"]
    user = messages[1]["content"]

    assert "wszystkie trzy pola tekstowe odpowiedzi muszą być napisane po polsku" in system
    assert "nie używaj określeń „w normie”, „typowe”, „bezpieczne”" in system
    assert "brak historycznego baseline'u lub punktu odniesienia" in system
    assert "`no_anomaly_detected`: brak jednoznacznej anomalii technicznej" in system
    assert "hierarchię: `anomaly` > `attention` > `no_anomaly_detected`" in system
    assert "operator_recommendation_pl" in system
    assert "data_quality_pl" in system
    assert "STOP i setpointy 0 V nie są" in system
    assert "Przeanalizuj poniższy pakiet danych" in user
    assert '"humidity_percent"' in user
    assert '"co2"' in user
    assert '"stddev"' not in user


def test_analysis_result_is_minimal_and_all_report_fields_are_required() -> None:
    result = _report_result()
    assert result.schema_version == 2
    assert result.status == "no_anomaly_detected"
    assert result.analysis_pl
    assert result.operator_recommendation_pl
    assert result.data_quality_pl

    with pytest.raises(ValidationError):
        VentilationAnalysisResult(
            status="no_anomaly_detected",
            analysis_pl="Brak widocznej anomalii.",
            operator_recommendation_pl="Kontynuować obserwację.",
        )


def test_compact_schema_is_flat_required_and_grammar_friendly() -> None:
    schema = VentilationAnalysisResult.model_json_schema()
    compact = compact_schema_for_ollama(schema)
    encoded = json.dumps(compact, sort_keys=True)

    assert '"$defs"' not in encoded
    assert '"$ref"' not in encoded
    assert '"maxLength"' not in encoded
    assert compact["properties"]["schema_version"]["enum"] == [2]
    assert set(compact["required"]) == {
        "status",
        "analysis_pl",
        "operator_recommendation_pl",
        "data_quality_pl",
    }


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
            content=_report_result().model_dump_json(),
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
    assert "Za mało danych" in result.result.analysis_pl
    assert repository.saved is not None
    assert repository.saved["raw_response"] is None
    assert repository.saved["sample_count"] == 1


def test_service_uses_structured_schema_without_thinking() -> None:
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

    assert result.result.status == "no_anomaly_detected"
    assert ollama.kwargs is not None
    assert ollama.kwargs["think"] is False
    assert ollama.kwargs["response_schema"]["properties"]["analysis_pl"]["type"] == "string"


def test_service_reuses_existing_analysis_without_calling_ollama() -> None:
    stored_result = _report_result("Zapisany wynik istniejącej analizy.")
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
    assert result.result.status == "no_anomaly_detected"
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
                    "content": _report_result().model_dump_json(),
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
    assert captured["json"]["think"] is False
    assert captured["json"]["format"] == schema
    assert captured["json"]["options"]["temperature"] == 0.0
    assert captured["timeout"] == 300.0
    assert result.model == "qwen3.6:35b"
    assert result.prompt_eval_count == 123
    assert result.eval_count == 45
    assert result.total_duration_ns == 999
