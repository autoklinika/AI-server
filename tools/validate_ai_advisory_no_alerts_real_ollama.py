from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from ai_bridge.adapters.ventilation.analysis import summarize_ventilation_window
from ai_bridge.adapters.ventilation.analysis_profile import build_compact_analysis_packet
from ai_bridge.adapters.ventilation.analysis_v12_2 import (
    ANALYSIS_THINK,
    PROMPT_VERSION,
    build_environment_prompt_from_compact,
    strip_alert_context,
)
from ai_bridge.analysis.service_v12_2 import VentilationAnalysisServiceV122
from ai_bridge.ollama.client import OllamaClient
from ai_bridge.settings import get_settings
from ai_bridge.storage.models import TelemetrySampleRecord


SOURCE_ID = "workshop-ventilation-cm5-01"
WINDOW_START = datetime(2026, 8, 21, 10, 0, tzinfo=timezone.utc)
WINDOW_END = datetime(2026, 8, 21, 10, 15, tzinfo=timezone.utc)
ALERT_CODE = "AERO_BUS_UNAVAILABLE"
ALERT_MESSAGE = "Rekuperator AERO niedostępny"


def make_sample(*, active_alarm: bool) -> TelemetrySampleRecord:
    alarms: list[dict[str, Any]] = []
    if active_alarm:
        alarms = [
            {
                "code": ALERT_CODE,
                "severity": "critical",
                "message": ALERT_MESSAGE,
                "active_since": WINDOW_START.isoformat(),
                "last_error": "timeout",
                "occurrences": 1,
                "alert_id": 4242,
                "source": "aero",
                "acknowledged": False,
                "acknowledged_at": None,
                "alert_v2": {"weight": 4},
            }
        ]

    return TelemetrySampleRecord(
        batch_record_id=1,
        source_id=SOURCE_ID,
        sample_id="pr10-real-ollama-alert-boundary",
        sequence=1,
        captured_at=WINDOW_START,
        received_at=WINDOW_START,
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


class MemoryRepository:
    def __init__(self, samples: list[TelemetrySampleRecord]) -> None:
        self.samples = samples
        self.saved: dict[str, Any] | None = None

    def get_existing(self, **_kwargs):
        return None

    def load_samples(self, **_kwargs):
        return self.samples

    def save_analysis(self, **kwargs):
        self.saved = kwargs


class RecordingOllama:
    def __init__(self, inner: OllamaClient) -> None:
        self.inner = inner
        self.kwargs: dict[str, Any] | None = None

    def chat_structured(self, **kwargs):
        self.kwargs = kwargs
        return self.inner.chat_structured(**kwargs)


def stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def prompt_hash(messages: list[dict[str, str]]) -> str:
    return hashlib.sha256(stable_json(messages).encode("utf-8")).hexdigest()


def main() -> int:
    settings = get_settings()
    real_ollama = OllamaClient(
        base_url=settings.ollama_url,
        timeout_seconds=settings.ollama_analysis_timeout_seconds,
    )
    if not real_ollama.is_available():
        raise RuntimeError(f"Ollama is not available at {settings.ollama_url}")

    alert_sample = make_sample(active_alarm=True)
    baseline_sample = make_sample(active_alarm=False)

    baseline_summary = summarize_ventilation_window(
        source_id=SOURCE_ID,
        window_start=WINDOW_START,
        window_end=WINDOW_END,
        samples=[baseline_sample],
    )
    baseline_compact = strip_alert_context(build_compact_analysis_packet(baseline_summary))
    baseline_messages = build_environment_prompt_from_compact(baseline_compact)

    repository = MemoryRepository([alert_sample])
    recording_ollama = RecordingOllama(real_ollama)
    service = VentilationAnalysisServiceV122(
        repository=repository,  # type: ignore[arg-type]
        ollama=recording_ollama,  # type: ignore[arg-type]
        model=settings.ollama_model,
        think=ANALYSIS_THINK,
        temperature=settings.analysis_temperature,
        min_samples=1,
    )

    run = service.analyze_window(
        source_id=SOURCE_ID,
        window_start=WINDOW_START,
        window_end=WINDOW_END,
    )

    if repository.saved is None:
        raise AssertionError("analysis result was not captured")
    if recording_ollama.kwargs is None:
        raise AssertionError("real Ollama call was not captured")

    audit_system = repository.saved["input_summary"]["system"]
    if audit_system["active_alarm_sample_count"] != 1:
        raise AssertionError(f"audit lost active alarm count: {audit_system}")
    if audit_system["active_alarm_codes"] != [ALERT_CODE]:
        raise AssertionError(f"audit lost active alarm code: {audit_system}")

    recorded_messages = recording_ollama.kwargs["messages"]
    if recorded_messages != baseline_messages:
        raise AssertionError(
            "alert-bearing sample changed the model prompt compared with the identical no-alert baseline"
        )

    serialized_prompt = stable_json(recorded_messages)
    serialized_result = stable_json(repository.saved["result"])
    forbidden = (
        ALERT_CODE,
        ALERT_MESSAGE,
        "active_alarm_codes",
        "active_alarm_sample_count",
        "Aktywny alarm",
        "alarmów CM5",
    )
    prompt_hits = [token for token in forbidden if token in serialized_prompt]
    result_hits = [token for token in forbidden if token in serialized_result]
    if prompt_hits:
        raise AssertionError(f"operator alert leaked into Qwen prompt: {prompt_hits}")
    if result_hits:
        raise AssertionError(f"operator alert leaked into advisory result: {result_hits}")

    output = {
        "ok": True,
        "validation": "pr10_real_ollama_alert_boundary",
        "prompt_version": run.prompt_version,
        "expected_prompt_version": "ventilation-v12.2.1-no-alert-context",
        "model": run.model,
        "ollama_url": settings.ollama_url,
        "audit": {
            "active_alarm_sample_count": audit_system["active_alarm_sample_count"],
            "active_alarm_codes": audit_system["active_alarm_codes"],
        },
        "model_input": {
            "identical_to_no_alert_baseline": recorded_messages == baseline_messages,
            "prompt_sha256": prompt_hash(recorded_messages),
            "forbidden_alert_hits": prompt_hits,
        },
        "advisory": {
            "status": run.result.status,
            "forbidden_alert_hits": result_hits,
            "operator_view": (
                None
                if run.result.operator_view is None
                else run.result.operator_view.model_dump(mode="json")
            ),
        },
        "ollama_response": {
            "raw_environmental_json": repository.saved["raw_response"],
            "prompt_eval_count": repository.saved["prompt_eval_count"],
            "eval_count": repository.saved["eval_count"],
            "total_duration_ns": repository.saved["total_duration_ns"],
        },
        "production_database_modified": False,
        "production_cache_modified": False,
    }

    if run.prompt_version != output["expected_prompt_version"]:
        raise AssertionError(
            f"unexpected prompt version {run.prompt_version!r}; "
            f"expected {output['expected_prompt_version']!r}"
        )

    print(json.dumps(output, ensure_ascii=False, indent=2))
    print("PASS: PR #10 real Qwen alert-boundary validation succeeded")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
