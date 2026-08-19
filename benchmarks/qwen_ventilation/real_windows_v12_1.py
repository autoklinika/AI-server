from __future__ import annotations

"""Read-only archived-real-window validation for v12.1 grounded decisions."""

from datetime import datetime
import json
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

from sqlalchemy import select


ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from ai_bridge.adapters.ventilation.analysis import summarize_ventilation_window  # noqa: E402
from ai_bridge.adapters.ventilation.analysis_profile import build_compact_analysis_packet  # noqa: E402
from ai_bridge.adapters.ventilation.analysis_v12_1 import (  # noqa: E402
    ANALYSIS_THINK,
    PROMPT_VERSION,
    EnvironmentalDecisionV121,
    build_environment_packet_from_compact,
    build_environment_prompt_from_compact,
    render_result,
    resolve_final_decision,
)
from ai_bridge.ollama.client import OllamaClient, compact_schema_for_ollama  # noqa: E402
from ai_bridge.settings import get_settings  # noqa: E402
from ai_bridge.storage.database import Database  # noqa: E402
from ai_bridge.storage.models import TelemetrySampleRecord  # noqa: E402


TZ = ZoneInfo("Europe/Warsaw")
RESULTS_DIR = ROOT / "benchmark_results" / "qwen_ventilation"
WINDOWS = [
    ("voc_bilateral_event", "2026-08-13T14:00:00+02:00", "2026-08-13T14:15:00+02:00"),
    ("pm_rise", "2026-08-13T16:15:00+02:00", "2026-08-13T16:30:00+02:00"),
    ("pm_fall", "2026-08-13T16:30:00+02:00", "2026-08-13T16:45:00+02:00"),
    ("sensor_bus_alarm_window", "2026-08-17T14:00:00+02:00", "2026-08-17T14:15:00+02:00"),
    ("voc_complex_with_aero_alarm", "2026-08-18T12:00:00+02:00", "2026-08-18T12:15:00+02:00"),
    ("recent_clean_reference", "2026-08-18T17:45:00+02:00", "2026-08-18T18:00:00+02:00"),
]


def _dt(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=TZ)


def main() -> int:
    settings = get_settings()
    db = Database(settings.database_url)
    client = OllamaClient(
        base_url=settings.ollama_url,
        timeout_seconds=settings.ollama_analysis_timeout_seconds,
    )
    response_schema = compact_schema_for_ollama(EnvironmentalDecisionV121.model_json_schema())

    report = {
        "profile": PROMPT_VERSION,
        "model": settings.ollama_model,
        "think": ANALYSIS_THINK,
        "source_id": settings.ventilation_source_id,
        "read_only": True,
        "writes_ventilation_analysis_runs": False,
        "windows": [],
    }

    try:
        for label, start_text, end_text in WINDOWS:
            start = _dt(start_text)
            end = _dt(end_text)
            with db.session() as session:
                rows = list(
                    session.scalars(
                        select(TelemetrySampleRecord)
                        .where(
                            TelemetrySampleRecord.source_id == settings.ventilation_source_id,
                            TelemetrySampleRecord.captured_at >= start,
                            TelemetrySampleRecord.captured_at < end,
                        )
                        .order_by(TelemetrySampleRecord.captured_at)
                    )
                )

            record = {
                "label": label,
                "window_start": start.isoformat(),
                "window_end": end.isoformat(),
                "sample_count": len(rows),
            }
            print("\n" + "=" * 90)
            print(f"{label}: samples={len(rows)}")

            if len(rows) < settings.analysis_min_samples:
                record.update(
                    {
                        "skipped": True,
                        "reason": f"sample_count={len(rows)} below gate {settings.analysis_min_samples}",
                    }
                )
                report["windows"].append(record)
                print(f"SKIP: {record['reason']}")
                continue

            summary = summarize_ventilation_window(
                source_id=settings.ventilation_source_id,
                window_start=start,
                window_end=end,
                samples=rows,
            )
            compact = build_compact_analysis_packet(summary)
            environment_packet = build_environment_packet_from_compact(compact)

            chat = client.chat_structured(
                model=settings.ollama_model,
                messages=build_environment_prompt_from_compact(compact),
                response_schema=response_schema,
                think=ANALYSIS_THINK,
                temperature=settings.analysis_temperature,
            )
            environmental = EnvironmentalDecisionV121.model_validate_json(chat.content)
            final = resolve_final_decision(compact, environmental)
            result = render_result(compact, environmental)

            duration = None if chat.total_duration_ns is None else round(chat.total_duration_ns / 1e9, 3)
            print(
                f"env_attention={environmental.environmental_attention} "
                f"final_status={final.status} reasons={final.reason_codes} "
                f"rec={final.recommendation_code}"
            )
            print(f"environment_facts={environmental.selected_fact_ids}")
            print(f"final_facts={final.selected_fact_ids}")
            print(json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2))
            print(f"tokens={chat.eval_count} duration={duration}s")

            record.update(
                {
                    "skipped": False,
                    "compact_packet": compact,
                    "environment_packet": environment_packet,
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
            report["windows"].append(record)
    finally:
        db.dispose()

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(TZ).strftime("%Y%m%dT%H%M%S%z")
    output = RESULTS_DIR / f"real_windows_v12_1_{stamp}.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n" + "=" * 90)
    print(f"Profile: {PROMPT_VERSION}")
    print(f"Model:   {settings.ollama_model}")
    print("DB writes: NONE")
    print(f"Report: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
