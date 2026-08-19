from __future__ import annotations

"""Two-call fast gate for the v12.1 grounded-decision architecture.

Technical alarms and data quality are now deterministic Python policy, so they do
not consume model calls here. Qwen is exercised only on the two semantic cases it
still owns: a stable environmental window and a clear PM rise.
"""

from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import run_v12_fast as previous  # noqa: E402

from ai_bridge.adapters.ventilation.analysis_v12_1 import (  # noqa: E402
    ANALYSIS_THINK,
    PROMPT_VERSION,
    EnvironmentalDecisionV121,
    build_environment_prompt_from_compact,
    render_result,
    resolve_final_decision,
)
from ai_bridge.ollama.client import OllamaClient, compact_schema_for_ollama  # noqa: E402
from ai_bridge.settings import get_settings  # noqa: E402


RESULTS_DIR = ROOT / "benchmark_results" / "qwen_ventilation"


def _packets() -> dict[str, dict[str, Any]]:
    return {item["id"]: item["packet"] for item in previous._scenario_packets()}


def main() -> int:
    settings = get_settings()
    client = OllamaClient(
        base_url=settings.ollama_url,
        timeout_seconds=settings.ollama_analysis_timeout_seconds,
    )
    response_schema = compact_schema_for_ollama(EnvironmentalDecisionV121.model_json_schema())
    packets = _packets()

    report: dict[str, Any] = {
        "profile": PROMPT_VERSION,
        "model": settings.ollama_model,
        "think": ANALYSIS_THINK,
        "model_calls": 2,
        "runs": [],
    }
    passed = 0

    semantic_cases = [
        ("stable", False),
        ("pm_rise", True),
    ]
    for scenario_id, expected_attention in semantic_cases:
        packet = packets[scenario_id]
        print(f"[{scenario_id}] model...", flush=True)
        chat = client.chat_structured(
            model=settings.ollama_model,
            messages=build_environment_prompt_from_compact(packet),
            response_schema=response_schema,
            think=ANALYSIS_THINK,
            temperature=settings.analysis_temperature,
        )
        environmental = EnvironmentalDecisionV121.model_validate_json(chat.content)
        final = resolve_final_decision(packet, environmental)
        result = render_result(packet, environmental)
        selected_reading = any(":reading:" in fact_id for fact_id in environmental.selected_fact_ids)
        checks = {
            "environmental_attention": environmental.environmental_attention == expected_attention,
            "final_status": final.status
            == ("attention" if expected_attention else "no_anomaly_detected"),
            "pm_fact_selected": scenario_id != "pm_rise" or selected_reading,
        }
        ok = all(checks.values())
        if ok:
            passed += 1
        duration = None if chat.total_duration_ns is None else round(chat.total_duration_ns / 1e9, 3)
        print(
            f"  {'PASS' if ok else 'FAIL'}: env_attention={environmental.environmental_attention} "
            f"final={final.status} facts={environmental.selected_fact_ids} "
            f"tokens={chat.eval_count} duration={duration}s",
            flush=True,
        )
        if not ok:
            print(f"  checks={checks}", flush=True)
        report["runs"].append(
            {
                "scenario": scenario_id,
                "passed": ok,
                "checks": checks,
                "environmental_decision": environmental.model_dump(mode="json"),
                "final_decision": final.model_dump(mode="json"),
                "result": result.model_dump(mode="json"),
                "metrics": {
                    "prompt_eval_count": chat.prompt_eval_count,
                    "eval_count": chat.eval_count,
                    "total_duration_seconds": duration,
                },
            }
        )

    # Deterministic cases: zero Ollama calls.
    deterministic_cases = [
        ("partial_missing", "attention", "data_quality_issue"),
        ("active_alarm", "anomaly", "technical_alarm"),
    ]
    for scenario_id, expected_status, expected_reason in deterministic_cases:
        packet = packets[scenario_id]
        environmental = EnvironmentalDecisionV121(environmental_attention=False)
        final = resolve_final_decision(packet, environmental)
        result = render_result(packet, environmental)
        checks = {
            "final_status": final.status == expected_status,
            "reason": expected_reason in final.reason_codes,
        }
        ok = all(checks.values())
        if ok:
            passed += 1
        print(
            f"[{scenario_id}] deterministic {'PASS' if ok else 'FAIL'}: "
            f"final={final.status} reasons={final.reason_codes}",
            flush=True,
        )
        report["runs"].append(
            {
                "scenario": scenario_id,
                "passed": ok,
                "checks": checks,
                "environmental_decision": environmental.model_dump(mode="json"),
                "final_decision": final.model_dump(mode="json"),
                "result": result.model_dump(mode="json"),
                "metrics": {"ollama_called": False},
            }
        )

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output = RESULTS_DIR / f"benchmark_v12_1_fast_{stamp}.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n=== V12.1 FAST GATE ===")
    print(f"Prompt:      {PROMPT_VERSION}")
    print("Model calls: 2")
    print(f"PASS:        {passed}/4")
    print(f"Report:      {output}")
    return 0 if passed == 4 else 1


if __name__ == "__main__":
    raise SystemExit(main())
