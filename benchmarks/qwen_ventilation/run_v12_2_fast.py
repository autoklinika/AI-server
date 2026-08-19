from __future__ import annotations

"""Two-call semantic gate for v12.2.

Only the two cases needed to prove the changed contract call Ollama:
- PM rise must still require environmental attention,
- the archived clean-reference pattern (PM/VOC falling) must not.
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

import run_v12_1_fast as previous  # noqa: E402

from ai_bridge.adapters.ventilation.analysis_v12_2 import (  # noqa: E402
    ANALYSIS_THINK,
    PROMPT_VERSION,
    EnvironmentalDecisionV122,
    build_environment_prompt_from_compact,
    render_result,
    resolve_final_decision,
)
from ai_bridge.ollama.client import OllamaClient, compact_schema_for_ollama  # noqa: E402
from ai_bridge.settings import get_settings  # noqa: E402


RESULTS_DIR = ROOT / "benchmark_results" / "qwen_ventilation"


def _metric(first: float, last: float) -> dict[str, Any]:
    delta = last - first
    return {
        "count": 180,
        "missing": 0,
        "mean": round((first + last) / 2, 4),
        "min": min(first, last),
        "max": max(first, last),
        "first": first,
        "last": last,
        "delta": delta,
        "slope_per_minute": round(delta / 15, 4),
    }


def _packets() -> dict[str, dict[str, Any]]:
    packets = previous._packets()
    clean = deepcopy(packets["stable"])
    clean["sensor_bus"]["nodes"]["1"]["readings"]["voc_index"] = _metric(21.0, 7.0)
    clean["sensor_bus"]["nodes"]["2"]["readings"]["voc_index"] = _metric(22.0, 6.0)
    clean["sensor_bus"]["nodes"]["1"]["readings"]["pm2_5_ug_m3"] = _metric(7.4, 3.1)
    clean["sensor_bus"]["nodes"]["2"]["readings"]["pm2_5_ug_m3"] = _metric(7.0, 3.2)
    clean["sensor_bus"]["nodes"]["1"]["readings"]["pm10_0_ug_m3"] = _metric(7.4, 3.1)
    clean["sensor_bus"]["nodes"]["2"]["readings"]["pm10_0_ug_m3"] = _metric(7.0, 3.2)
    packets["recent_clean_reference"] = clean
    return packets


def main() -> int:
    settings = get_settings()
    client = OllamaClient(
        base_url=settings.ollama_url,
        timeout_seconds=settings.ollama_analysis_timeout_seconds,
    )
    response_schema = compact_schema_for_ollama(EnvironmentalDecisionV122.model_json_schema())
    packets = _packets()
    cases = [("pm_rise", True, "attention"), ("recent_clean_reference", False, "no_anomaly_detected")]

    report: dict[str, Any] = {
        "profile": PROMPT_VERSION,
        "model": settings.ollama_model,
        "think": ANALYSIS_THINK,
        "model_calls": 2,
        "runs": [],
    }
    passed = 0

    for scenario_id, expected_attention, expected_status in cases:
        packet = packets[scenario_id]
        print(f"[{scenario_id}] model...", flush=True)
        chat = client.chat_structured(
            model=settings.ollama_model,
            messages=build_environment_prompt_from_compact(packet),
            response_schema=response_schema,
            think=ANALYSIS_THINK,
            temperature=settings.analysis_temperature,
        )
        environmental = EnvironmentalDecisionV122.model_validate_json(chat.content)
        final = resolve_final_decision(packet, environmental)
        result = render_result(packet, environmental)
        selected_reading = any(":reading:" in fact_id for fact_id in environmental.selected_fact_ids)
        checks = {
            "environmental_attention": environmental.environmental_attention == expected_attention,
            "final_status": final.status == expected_status,
            "fact_selection": (
                selected_reading if expected_attention else environmental.selected_fact_ids == []
            ),
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

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output = RESULTS_DIR / f"benchmark_v12_2_fast_{stamp}.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n=== V12.2 FAST GATE ===")
    print(f"Prompt:      {PROMPT_VERSION}")
    print("Model calls: 2")
    print(f"PASS:        {passed}/2")
    print(f"Report:      {output}")
    return 0 if passed == 2 else 1


if __name__ == "__main__":
    raise SystemExit(main())
