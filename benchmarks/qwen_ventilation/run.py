from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from ai_bridge.adapters.ventilation.analysis_profile import (  # noqa: E402
    ANALYSIS_THINK,
    PROMPT_VERSION,
    SYSTEM_PROMPT,
)
from ai_bridge.analysis.schemas import VentilationAnalysisResult  # noqa: E402
from ai_bridge.ollama.client import (  # noqa: E402
    OllamaClient,
    compact_schema_for_ollama,
)
from ai_bridge.settings import get_settings  # noqa: E402


SCENARIOS_FILE = Path(__file__).with_name("scenarios.json")
DEFAULT_RESULTS_DIR = ROOT / "benchmark_results" / "qwen_ventilation"

COMMON_FORBIDDEN = [
    {
        "name": "external_standard_WHO",
        "field": "all",
        "pattern": r"\bWHO\b",
    },
    {
        "name": "unsupported_ppm_unit",
        "field": "all",
        "pattern": r"\bppm\b",
    },
    {
        "name": "unsupported_ppb_unit",
        "field": "all",
        "pattern": r"\bppb\b",
    },
    {
        "name": "meta_offer",
        "field": "all",
        "pattern": r"(?:jeśli chcesz|mogę (?:też |również )?(?:przygotować|zrobić|wygenerować))",
    },
]


def _metric(
    *,
    mean: float,
    minimum: float,
    maximum: float,
    delta: float = 0.0,
    slope: float = 0.0,
    count: int = 180,
    missing: int = 0,
) -> dict[str, Any]:
    return {
        "count": count,
        "missing": missing,
        "mean": mean,
        "min": minimum,
        "max": maximum,
        "delta": delta,
        "slope_per_minute": slope,
    }


def _base_node(*, temperature: float) -> dict[str, Any]:
    return {
        "samples_present": 180,
        "online_ratio": 1.0,
        "measurement_valid_ratio": 1.0,
        "measurement_stale_ratio": 0.0,
        "sensor_present_ratio": 1.0,
        "readings": {
            "pm1_0_ug_m3": _metric(mean=3.0, minimum=2.0, maximum=4.0),
            "pm2_5_ug_m3": _metric(mean=4.0, minimum=3.0, maximum=5.0),
            "pm4_0_ug_m3": _metric(mean=5.0, minimum=4.0, maximum=6.0),
            "pm10_0_ug_m3": _metric(mean=7.0, minimum=6.0, maximum=8.0),
            "humidity_percent": _metric(mean=45.0, minimum=44.0, maximum=46.0),
            "temperature_celsius": _metric(
                mean=temperature,
                minimum=temperature - 0.2,
                maximum=temperature + 0.2,
            ),
            "voc_index": _metric(mean=95.0, minimum=90.0, maximum=100.0),
            "nox_index": _metric(mean=1.0, minimum=1.0, maximum=1.0),
        },
        "diagnostic_counter_deltas": {
            "sensor_errors": 0,
            "modbus_service_errors": 0,
            "communication_errors": 0,
            "consecutive_failures": 0,
            "invalid_measurements": 0,
            "stale_measurements": 0,
            "map_version_errors": 0,
        },
        "latest_error": None,
    }


def base_packet() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "source_id": "benchmark-ai-server",
        "window": {
            "start": "2026-08-13T12:00:00+00:00",
            "end": "2026-08-13T12:15:00+00:00",
            "sample_count": 180,
            "capture_span_seconds": 895.0,
        },
        "analysis_context": {
            "historical_baseline_available": False,
            "expected_operating_state_known": False,
        },
        "measurement_capabilities": {
            "present_in_packet": [
                "humidity_percent",
                "nox_index",
                "pm1_0_ug_m3",
                "pm2_5_ug_m3",
                "pm4_0_ug_m3",
                "pm10_0_ug_m3",
                "temperature_celsius",
                "voc_index",
            ],
            "not_provided_by_system": ["co2", "fan_rpm", "airflow"],
        },
        "controller": {
            "latest_mode": "MANUAL",
            "mode_counts": {"MANUAL": 180},
            "setpoints": {
                "supply_voltage": {
                    "mean": 3.0,
                    "min": 3.0,
                    "max": 3.0,
                    "delta": 0.0,
                },
                "extract_voltage": {
                    "mean": 3.0,
                    "min": 3.0,
                    "max": 3.0,
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
            "nodes": {
                "1": _base_node(temperature=21.0),
                "2": _base_node(temperature=20.5),
            },
        },
    }


def deep_merge(target: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(target)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = deepcopy(value)
    return result


def load_scenarios() -> list[dict[str, Any]]:
    data = json.loads(SCENARIOS_FILE.read_text(encoding="utf-8"))
    scenarios = data.get("scenarios")
    if not isinstance(scenarios, list) or not scenarios:
        raise RuntimeError("scenarios.json does not contain a non-empty scenarios list")
    ids = [scenario.get("id") for scenario in scenarios]
    if len(ids) != len(set(ids)):
        raise RuntimeError("Scenario IDs must be unique")
    return scenarios


def messages_for_packet(packet: dict[str, Any]) -> list[dict[str, str]]:
    user = (
        "Przeanalizuj poniższy pakiet danych. "
        f"Wersja profilu: {PROMPT_VERSION}\n\n"
        + json.dumps(packet, ensure_ascii=False, sort_keys=True, indent=2)
    )
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]


def text_field(result: VentilationAnalysisResult, field: str) -> str:
    if field == "all":
        return "\n".join(
            [
                result.analysis_pl,
                result.operator_recommendation_pl,
                result.data_quality_pl,
            ]
        )
    value = getattr(result, field, None)
    if not isinstance(value, str):
        raise ValueError(f"Unsupported benchmark text field: {field}")
    return value


def regex_match(pattern: str, text: str) -> bool:
    return re.search(pattern, text, flags=re.IGNORECASE | re.DOTALL) is not None


def evaluate(
    scenario: dict[str, Any],
    result: VentilationAnalysisResult,
) -> tuple[bool, list[dict[str, Any]]]:
    checks: list[dict[str, Any]] = []

    allowed_status = scenario.get("allowed_status", [])
    status_ok = result.status in allowed_status
    checks.append(
        {
            "name": "allowed_status",
            "passed": status_ok,
            "detail": f"status={result.status!r}, allowed={allowed_status!r}",
        }
    )

    for requirement in scenario.get("must_match", []):
        field = requirement.get("field", "all")
        patterns = requirement.get("patterns", [])
        mode = requirement.get("mode", "any")
        text = text_field(result, field)
        matches = [regex_match(pattern, text) for pattern in patterns]
        passed = all(matches) if mode == "all" else any(matches)
        checks.append(
            {
                "name": requirement.get("name", "must_match"),
                "passed": passed,
                "detail": {
                    "field": field,
                    "mode": mode,
                    "patterns": patterns,
                    "matches": matches,
                },
            }
        )

    forbidden = [*COMMON_FORBIDDEN, *scenario.get("must_not_match", [])]
    for rule in forbidden:
        field = rule.get("field", "all")
        pattern = rule["pattern"]
        text = text_field(result, field)
        hit = regex_match(pattern, text)
        checks.append(
            {
                "name": rule.get("name", "must_not_match"),
                "passed": not hit,
                "detail": {
                    "field": field,
                    "pattern": pattern,
                    "matched": hit,
                },
            }
        )

    return all(check["passed"] for check in checks), checks


def parser() -> argparse.ArgumentParser:
    settings = get_settings()
    p = argparse.ArgumentParser(
        description=(
            "Repeatable semantic benchmark for the active AI Server Qwen ventilation profile"
        )
    )
    p.add_argument("--model", default=settings.ollama_model)
    p.add_argument("--ollama-url", default=settings.ollama_url)
    p.add_argument(
        "--timeout",
        type=float,
        default=settings.ollama_analysis_timeout_seconds,
    )
    p.add_argument(
        "--temperature",
        type=float,
        default=settings.analysis_temperature,
    )
    p.add_argument(
        "--think",
        action=argparse.BooleanOptionalAction,
        default=ANALYSIS_THINK,
    )
    p.add_argument(
        "--scenario",
        action="append",
        default=[],
        help="Run only the selected scenario ID; may be supplied more than once",
    )
    p.add_argument("--repeat", type=int, default=1)
    p.add_argument("--list", action="store_true", help="List scenarios and exit")
    p.add_argument(
        "--results-dir",
        type=Path,
        default=DEFAULT_RESULTS_DIR,
    )
    p.add_argument("--stop-on-fail", action="store_true")
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and display selected scenarios without calling Ollama",
    )
    return p


def main() -> int:
    args = parser().parse_args()
    if args.repeat < 1:
        raise SystemExit("--repeat must be >= 1")

    scenarios = load_scenarios()
    if args.list:
        for scenario in scenarios:
            print(f"{scenario['id']}: {scenario['description']}")
        return 0

    wanted = set(args.scenario)
    selected = [
        scenario for scenario in scenarios if not wanted or scenario["id"] in wanted
    ]
    missing = wanted - {scenario["id"] for scenario in selected}
    if missing:
        raise SystemExit(f"Unknown scenario IDs: {', '.join(sorted(missing))}")

    packets = {
        scenario["id"]: deep_merge(base_packet(), scenario.get("overrides", {}))
        for scenario in selected
    }

    if args.dry_run:
        print(
            json.dumps(
                {
                    "prompt_version": PROMPT_VERSION,
                    "think": args.think,
                    "temperature": args.temperature,
                    "scenario_ids": [scenario["id"] for scenario in selected],
                    "packets": packets,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    client = OllamaClient(
        base_url=args.ollama_url,
        timeout_seconds=args.timeout,
    )
    response_schema = compact_schema_for_ollama(
        VentilationAnalysisResult.model_json_schema()
    )

    report: dict[str, Any] = {
        "benchmark_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "prompt_version": PROMPT_VERSION,
        "model": args.model,
        "ollama_url": args.ollama_url,
        "think": args.think,
        "temperature": args.temperature,
        "repeat": args.repeat,
        "runs": [],
    }

    total = 0
    passed = 0
    stop = False

    for scenario in selected:
        if stop:
            break
        packet = packets[scenario["id"]]
        for repetition in range(1, args.repeat + 1):
            print(
                f"[{scenario['id']}] run {repetition}/{args.repeat}...",
                flush=True,
            )
            total += 1
            run_record: dict[str, Any] = {
                "scenario_id": scenario["id"],
                "description": scenario["description"],
                "repetition": repetition,
            }
            try:
                chat = client.chat_structured(
                    model=args.model,
                    messages=messages_for_packet(packet),
                    response_schema=response_schema,
                    think=args.think,
                    temperature=args.temperature,
                )
                result = VentilationAnalysisResult.model_validate_json(chat.content)
                run_passed, checks = evaluate(scenario, result)
                if run_passed:
                    passed += 1
                duration_s = (
                    None
                    if chat.total_duration_ns is None
                    else chat.total_duration_ns / 1_000_000_000
                )
                tokens_per_second = None
                if duration_s and chat.eval_count:
                    tokens_per_second = round(chat.eval_count / duration_s, 3)
                run_record.update(
                    {
                        "passed": run_passed,
                        "checks": checks,
                        "result": result.model_dump(mode="json"),
                        "raw_content": chat.content,
                        "metrics": {
                            "prompt_eval_count": chat.prompt_eval_count,
                            "eval_count": chat.eval_count,
                            "total_duration_seconds": None
                            if duration_s is None
                            else round(duration_s, 3),
                            "eval_tokens_per_total_second": tokens_per_second,
                        },
                    }
                )
                label = "PASS" if run_passed else "FAIL"
                print(
                    f"  {label}: status={result.status} "
                    f"tokens={chat.eval_count} duration={duration_s}",
                    flush=True,
                )
                if not run_passed:
                    for check in checks:
                        if not check["passed"]:
                            print(f"    - {check['name']}: {check['detail']}")
            except Exception as exc:  # benchmark must record model/runtime failures
                run_record.update(
                    {
                        "passed": False,
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )
                print(f"  ERROR: {type(exc).__name__}: {exc}", flush=True)

            report["runs"].append(run_record)
            if args.stop_on_fail and not run_record.get("passed", False):
                stop = True
                break

    report["summary"] = {
        "runs_total": total,
        "runs_passed": passed,
        "runs_failed": total - passed,
        "pass_rate": 0.0 if total == 0 else round(passed / total, 4),
    }

    args.results_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output = args.results_dir / f"benchmark_{timestamp}.json"
    output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print("\n=== BENCHMARK SUMMARY ===")
    print(f"Prompt: {PROMPT_VERSION}")
    print(f"Model:  {args.model}")
    print(f"PASS:   {passed}/{total}")
    print(f"Report: {output}")

    return 0 if passed == total else 2


if __name__ == "__main__":
    raise SystemExit(main())
