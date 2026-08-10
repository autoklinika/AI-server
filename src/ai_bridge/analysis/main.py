from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
import logging

from ai_bridge.analysis.service import VentilationAnalysisService, aligned_window
from ai_bridge.ollama.client import OllamaClient
from ai_bridge.settings import get_settings
from ai_bridge.storage.analysis_repository import VentilationAnalysisRepository
from ai_bridge.storage.database import Database


def _aware_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise argparse.ArgumentTypeError("Datetime must include timezone information")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    settings = get_settings()
    parser = argparse.ArgumentParser(
        description="Run one advisory Qwen analysis for a ventilation telemetry window"
    )
    parser.add_argument(
        "--source-id",
        default=settings.ventilation_source_id,
    )
    parser.add_argument(
        "--window-minutes",
        type=int,
        default=settings.analysis_window_minutes,
    )
    parser.add_argument(
        "--end-at",
        type=_aware_datetime,
        default=None,
        help=(
            "Optional end of analysis window as ISO 8601. "
            "Without it the last completed aligned window is used."
        ),
    )
    parser.add_argument("--log-level", default=settings.log_level)
    return parser


def main() -> int:
    settings = get_settings()
    args = build_parser().parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if args.end_at is None:
        window_start, window_end = aligned_window(
            datetime.now(timezone.utc),
            args.window_minutes,
        )
    else:
        window_end = args.end_at.astimezone(timezone.utc)
        window_start = window_end - timedelta(minutes=args.window_minutes)

    database = Database(settings.database_url)
    try:
        repository = VentilationAnalysisRepository(database)
        ollama = OllamaClient(
            base_url=settings.ollama_url,
            timeout_seconds=settings.ollama_analysis_timeout_seconds,
        )
        service = VentilationAnalysisService(
            repository=repository,
            ollama=ollama,
            model=settings.ollama_model,
            think=settings.analysis_think,
            temperature=settings.analysis_temperature,
            min_samples=settings.analysis_min_samples,
        )
        run = service.analyze_window(
            source_id=args.source_id,
            window_start=window_start,
            window_end=window_end,
        )
    finally:
        database.dispose()

    output = {
        "analysis_id": run.analysis_id,
        "source_id": run.source_id,
        "window_start": run.window_start.isoformat(),
        "window_end": run.window_end.isoformat(),
        "sample_count": run.sample_count,
        "model": run.model,
        "prompt_version": run.prompt_version,
        "reused_existing": run.reused_existing,
        "result": run.result.model_dump(mode="json"),
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
