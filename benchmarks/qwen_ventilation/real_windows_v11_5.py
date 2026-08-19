from __future__ import annotations

"""Read-only validation of Qwen v11.5 on archived real telemetry windows.

The script reads telemetry from the configured database and calls Ollama directly.
It does NOT use VentilationAnalysisService and does NOT write to
ventilation_analysis_runs.
"""

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
from ai_bridge.adapters.ventilation.analysis_profile import (  # noqa: E402
    ANALYSIS_THINK,
    PROMPT_VERSION,
    build_compact_analysis_packet,
    build_ventilation_prompt,
)
from ai_bridge.analysis.schemas import VentilationAnalysisResult  # noqa: E402
from ai_bridge.ollama.client import (  # noqa: E402
    OllamaClient,
    compact_schema_for_ollama,
)
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
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=TZ)
    return parsed


def _short_facts(packet: dict) -> dict:
    controller = packet.get("controller", {})
    sensor_bus = packet.get("sensor_bus", {})
    nodes = sensor_bus.get("nodes", {})

    compact_nodes = {}
    for node_id, node in nodes.items():
        readings = node.get("readings", {})
        compact_nodes[node_id] = {
            "online_ratio": node.get("online_ratio"),
            "measurement_valid_ratio": node.get("measurement_valid_ratio"),
            "measurement_stale_ratio": node.get("measurement_stale_ratio"),
            "consecutive_failures_max": node.get("consecutive_failures_max"),
            "diagnostic_counter_deltas": node.get("diagnostic_counter_deltas"),
            "pm2_5": readings.get("pm2_5_ug_m3"),
            "pm10": readings.get("pm10_0_ug_m3"),
            "voc": readings.get("voc_index"),
            "nox": readings.get("nox_index"),
            "temperature": readings.get("temperature_celsius"),
        }

    return {
        "controller_mode": controller.get("latest_mode"),
        "setpoints": controller.get("setpoints"),
        "active_alarm_sample_count": controller.get("active_alarm_sample_count"),
        "active_alarm_codes": controller.get("active_alarm_codes"),
        "sensor_bus_ready_ratio": sensor_bus.get("ready_ratio"),
        "worker_alive_ratio": sensor_bus.get("worker_alive_ratio"),
        "worker_restarts_max": sensor_bus.get("worker_restarts_max"),
        "sensor_bus_latest_error": sensor_bus.get("latest_error"),
        "nodes": compact_nodes,
    }


def main() -> int:
    settings = get_settings()
    db = Database(settings.database_url)
    ollama = OllamaClient(
        base_url=settings.ollama_url,
        timeout_seconds=settings.ollama_analysis_timeout_seconds,
    )
    response_schema = compact_schema_for_ollama(
        VentilationAnalysisResult.model_json_schema()
    )

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
                            TelemetrySampleRecord.source_id
                            == settings.ventilation_source_id,
                            TelemetrySampleRecord.captured_at >= start,
                            TelemetrySampleRecord.captured_at < end,
                        )
                        .order_by(TelemetrySampleRecord.captured_at)
                    )
                )

            print("\n" + "=" * 100)
            print(f"{label}: {start.isoformat()} -> {end.isoformat()}")
            print(f"samples: {len(rows)}")

            record = {
                "label": label,
                "window_start": start.isoformat(),
                "window_end": end.isoformat(),
                "sample_count": len(rows),
            }

            if len(rows) < settings.analysis_min_samples:
                record["skipped"] = True
                record["reason"] = (
                    f"sample_count={len(rows)} below gate "
                    f"{settings.analysis_min_samples}"
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
            packet = build_compact_analysis_packet(summary)
            facts = _short_facts(packet)

            print("--- deterministic facts ---")
            print(json.dumps(facts, ensure_ascii=False, indent=2))
            print("--- qwen ---", flush=True)

            chat = ollama.chat_structured(
                model=settings.ollama_model,
                messages=build_ventilation_prompt(summary),
                response_schema=response_schema,
                think=ANALYSIS_THINK,
                temperature=settings.analysis_temperature,
            )
            result = VentilationAnalysisResult.model_validate_json(chat.content)

            duration_seconds = (
                None
                if chat.total_duration_ns is None
                else round(chat.total_duration_ns / 1_000_000_000, 3)
            )

            print(json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2))
            print(
                f"status={result.status} tokens={chat.eval_count} "
                f"duration={duration_seconds}s"
            )

            record.update(
                {
                    "skipped": False,
                    "deterministic_facts": facts,
                    "compact_packet": packet,
                    "result": result.model_dump(mode="json"),
                    "metrics": {
                        "prompt_eval_count": chat.prompt_eval_count,
                        "eval_count": chat.eval_count,
                        "total_duration_seconds": duration_seconds,
                    },
                }
            )
            report["windows"].append(record)
    finally:
        db.dispose()

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(TZ).strftime("%Y%m%dT%H%M%S%z")
    output = RESULTS_DIR / f"real_windows_v11_5_{stamp}.json"
    output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print("\n" + "=" * 100)
    print(f"Profile: {PROMPT_VERSION}")
    print(f"Model:   {settings.ollama_model}")
    print("DB writes: NONE")
    print(f"Report: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
