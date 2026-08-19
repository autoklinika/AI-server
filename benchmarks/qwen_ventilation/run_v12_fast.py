from __future__ import annotations

"""Fast semantic gate for the v12 structured-decision architecture.

Only four high-value cases call Ollama. Numerical prose, data-quality wording and
recommendation text are tested deterministically by pytest instead of spending
model time re-generating them across the old 18-scenario free-text suite.
"""

from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from ai_bridge.adapters.ventilation.analysis_v12 import (  # noqa: E402
    ANALYSIS_THINK,
    PROMPT_VERSION,
    VentilationDecisionV12,
    build_decision_prompt_from_compact,
    render_result,
    validate_decision,
)
from ai_bridge.ollama.client import OllamaClient, compact_schema_for_ollama  # noqa: E402
from ai_bridge.settings import get_settings  # noqa: E402


RESULTS_DIR = ROOT / "benchmark_results" / "qwen_ventilation"


def _metric(first: float, last: float, *, missing: int = 0, count: int = 180) -> dict[str, Any]:
    delta = last - first
    return {
        "count": count,
        "missing": missing,
        "mean": round((first + last) / 2, 4),
        "min": min(first, last),
        "max": max(first, last),
        "first": first,
        "last": last,
        "delta": delta,
        "slope_per_minute": round(delta / 15, 4),
    }


def _node(*, voc_first: float = 20.0, voc_last: float = 20.0, voc_missing: int = 0) -> dict[str, Any]:
    return {
        "samples_present": 180,
        "online_ratio": 1.0,
        "measurement_valid_ratio": 1.0,
        "measurement_stale_ratio": 0.0,
        "sensor_present_ratio": 1.0,
        "diagnostic_counter_deltas": {
            "sensor_errors": 0,
            "modbus_service_errors": 0,
            "communication_errors": 0,
            "invalid_measurements": 0,
            "stale_measurements": 0,
            "map_version_errors": 0,
        },
        "consecutive_failures_max": 0,
        "latest_error": None,
        "readings": {
            "pm1_0_ug_m3": _metric(3.0, 3.0),
            "pm2_5_ug_m3": _metric(4.0, 4.0),
            "pm4_0_ug_m3": _metric(5.0, 5.0),
            "pm10_0_ug_m3": _metric(7.0, 7.0),
            "humidity_percent": _metric(45.0, 45.0),
            "temperature_celsius": _metric(22.0, 22.0),
            "voc_index": _metric(
                voc_first,
                voc_last,
                missing=voc_missing,
                count=180 - voc_missing,
            ),
            "nox_index": _metric(1.0, 1.0),
        },
    }


def _base_packet() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "source_id": "benchmark-ai-server",
        "window": {
            "start": "2026-08-19T10:00:00+02:00",
            "end": "2026-08-19T10:15:00+02:00",
            "sample_count": 180,
            "capture_span_seconds": 897.0,
        },
        "analysis_context": {
            "historical_baseline_available": False,
            "expected_operating_state_known": False,
        },
        "measurement_capabilities": {
            "present_in_packet": [
                "humidity_percent",
                "nox_index",
                "pm10_0_ug_m3",
                "pm1_0_ug_m3",
                "pm2_5_ug_m3",
                "pm4_0_ug_m3",
                "temperature_celsius",
                "voc_index",
            ],
            "not_provided_by_system": ["co2", "airflow"],
            "excluded_from_current_analysis_packet": ["fan_rpm", "tacho"],
        },
        "controller": {
            "latest_mode": "MANUAL",
            "mode_counts": {"MANUAL": 180},
            "setpoints": {
                "supply_voltage": {
                    "mean": 6.0,
                    "min": 6.0,
                    "max": 6.0,
                    "first": 6.0,
                    "last": 6.0,
                    "delta": 0.0,
                },
                "extract_voltage": {
                    "mean": 7.0,
                    "min": 7.0,
                    "max": 7.0,
                    "first": 7.0,
                    "last": 7.0,
                    "delta": 0.0,
                },
            },
            "hardware_ready_ratio": 1.0,
            "output_state_known_ratio": 1.0,
            "consecutive_hardware_failures_max": 0,
            "active_alarm_sample_count": 0,
            "active_alarm_codes": [],
        },
        "sensor_bus": {
            "ready_ratio": 1.0,
            "worker_alive_ratio": 1.0,
            "worker_restarts_max": 0,
            "latest_error": None,
            "nodes": {"1": _node(), "2": _node()},
        },
    }


def _scenario_packets() -> list[dict[str, Any]]:
    stable = _base_packet()

    pm_rise = deepcopy(_base_packet())
    pm_rise["controller"]["setpoints"]["supply_voltage"].update(
        {"mean": 4.8889, "min": 3.0, "max": 8.0, "first": 8.0, "last": 5.0, "delta": -3.0}
    )
    pm_rise["controller"]["setpoints"]["extract_voltage"].update(
        {"mean": 5.7222, "min": 3.0, "max": 8.5, "first": 8.5, "last": 6.0, "delta": -2.5}
    )
    pm_rise["sensor_bus"]["nodes"]["1"]["readings"]["pm2_5_ug_m3"] = _metric(4.4, 86.6)
    pm_rise["sensor_bus"]["nodes"]["1"]["readings"]["pm10_0_ug_m3"] = _metric(4.9, 163.4)
    pm_rise["sensor_bus"]["nodes"]["2"]["readings"]["pm2_5_ug_m3"] = _metric(4.8, 80.2)
    pm_rise["sensor_bus"]["nodes"]["2"]["readings"]["pm10_0_ug_m3"] = _metric(5.2, 152.9)
    pm_rise["sensor_bus"]["nodes"]["1"]["readings"]["voc_index"] = _metric(80.0, 32.0)
    pm_rise["sensor_bus"]["nodes"]["2"]["readings"]["voc_index"] = _metric(87.0, 43.0)

    partial_missing = deepcopy(_base_packet())
    partial_missing["sensor_bus"]["nodes"]["1"]["readings"]["voc_index"] = _metric(
        95.0, 96.0, missing=10, count=170
    )

    alarm = deepcopy(_base_packet())
    alarm["controller"].update(
        {
            "latest_mode": "STOP",
            "mode_counts": {"STOP": 180},
            "active_alarm_sample_count": 178,
            "active_alarm_codes": ["AERO_BUS_UNAVAILABLE"],
        }
    )
    for channel in ("supply_voltage", "extract_voltage"):
        alarm["controller"]["setpoints"][channel].update(
            {"mean": 0.0, "min": 0.0, "max": 0.0, "first": 0.0, "last": 0.0, "delta": 0.0}
        )

    return [
        {
            "id": "stable",
            "packet": stable,
            "expected_status": "no_anomaly_detected",
            "required_reason": "no_significant_issue",
            "allowed_recommendations": {"none"},
            "required_any_fact_ids": set(),
        },
        {
            "id": "pm_rise",
            "packet": pm_rise,
            "expected_status": "attention",
            "required_reason": "environmental_change",
            "allowed_recommendations": {"observe_next_windows", "none"},
            "required_any_fact_ids": {
                "node:1:reading:pm2_5_ug_m3",
                "node:1:reading:pm10_0_ug_m3",
                "node:2:reading:pm2_5_ug_m3",
                "node:2:reading:pm10_0_ug_m3",
            },
        },
        {
            "id": "partial_missing",
            "packet": partial_missing,
            "expected_status": "attention",
            "required_reason": "data_quality_issue",
            "allowed_recommendations": {"observe_next_windows", "none"},
            "required_any_fact_ids": {"node:1:reading:voc_index"},
        },
        {
            "id": "active_alarm",
            "packet": alarm,
            "expected_status": "anomaly",
            "required_reason": "technical_alarm",
            "allowed_recommendations": {"diagnose_active_alarm"},
            "required_any_fact_ids": {"alarm:AERO_BUS_UNAVAILABLE"},
        },
    ]


def main() -> int:
    settings = get_settings()
    client = OllamaClient(
        base_url=settings.ollama_url,
        timeout_seconds=settings.ollama_analysis_timeout_seconds,
    )
    response_schema = compact_schema_for_ollama(VentilationDecisionV12.model_json_schema())

    report: dict[str, Any] = {
        "profile": PROMPT_VERSION,
        "model": settings.ollama_model,
        "think": ANALYSIS_THINK,
        "runs": [],
    }
    passed = 0
    scenarios = _scenario_packets()

    for scenario in scenarios:
        print(f"[{scenario['id']}]...", flush=True)
        chat = client.chat_structured(
            model=settings.ollama_model,
            messages=build_decision_prompt_from_compact(scenario["packet"]),
            response_schema=response_schema,
            think=ANALYSIS_THINK,
            temperature=settings.analysis_temperature,
        )
        decision = VentilationDecisionV12.model_validate_json(chat.content)
        error: str | None = None
        try:
            validate_decision(scenario["packet"], decision)
        except ValueError as exc:
            error = str(exc)

        selected = set(decision.selected_fact_ids)
        required_any = scenario["required_any_fact_ids"]
        checks = {
            "decision_valid": error is None,
            "status": decision.status == scenario["expected_status"],
            "reason": scenario["required_reason"] in decision.reason_codes,
            "recommendation": decision.recommendation_code in scenario["allowed_recommendations"],
            "fact_selection": not required_any or bool(selected.intersection(required_any)),
        }
        run_passed = all(checks.values())
        if run_passed:
            passed += 1

        result = None
        if error is None:
            result = render_result(scenario["packet"], decision).model_dump(mode="json")

        duration = None if chat.total_duration_ns is None else round(chat.total_duration_ns / 1e9, 3)
        report["runs"].append(
            {
                "scenario": scenario["id"],
                "passed": run_passed,
                "checks": checks,
                "validation_error": error,
                "decision": decision.model_dump(mode="json"),
                "result": result,
                "metrics": {
                    "prompt_eval_count": chat.prompt_eval_count,
                    "eval_count": chat.eval_count,
                    "total_duration_seconds": duration,
                },
            }
        )
        label = "PASS" if run_passed else "FAIL"
        print(
            f"  {label}: status={decision.status} reasons={decision.reason_codes} "
            f"rec={decision.recommendation_code} facts={decision.selected_fact_ids} "
            f"tokens={chat.eval_count} duration={duration}s",
            flush=True,
        )
        if not run_passed:
            print(f"  checks={checks} validation_error={error}", flush=True)

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output = RESULTS_DIR / f"benchmark_v12_fast_{stamp}.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n=== V12 FAST GATE ===")
    print(f"Prompt: {PROMPT_VERSION}")
    print(f"PASS:   {passed}/{len(scenarios)}")
    print(f"Report: {output}")
    return 0 if passed == len(scenarios) else 1


if __name__ == "__main__":
    raise SystemExit(main())
