from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
import logging

from ai_bridge.domains.wvc.profiles.analysis_v12_2 import ANALYSIS_THINK
from ai_bridge.domains.wvc.analysis.service import aligned_window
from ai_bridge.domains.wvc.analysis.service_v12_2 import VentilationAnalysisServiceV122
from ai_bridge.providers.ollama import OllamaAdapter
from ai_bridge.settings import get_settings
from ai_bridge.domains.wvc.storage.analysis_repository import VentilationAnalysisRepository
from ai_bridge.storage.database import Database
from ai_bridge.domains.wvc.policy import WVCAnalysisPolicy


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
        use_gateway = settings.analysis_use_gateway
        inference_url = settings.gateway_url if use_gateway else settings.ollama_url
        if use_gateway:
            # Use the existing WVC contract so v2 records reasoning/wvc rather
            # than generic chat/shared. Accept an already namespaced legacy URL.
            inference_url = inference_url.rstrip("/")
            if not inference_url.endswith("/clients/ventilation"):
                inference_url += "/clients/ventilation"
        logging.info(
            "Ventilation inference route=%s url=%s",
            "ai-gateway" if use_gateway else "direct-ollama",
            inference_url,
        )
        llm = OllamaAdapter.from_endpoint(
            base_url=inference_url,
            default_model=settings.ollama_model,
            timeout_seconds=settings.ollama_analysis_timeout_seconds,
            request_source="ventilation" if use_gateway else None,
            request_priority=(
                settings.gateway_priority_ventilation if use_gateway else None
            ),
            node_id=settings.node_id,
        )
        service = VentilationAnalysisServiceV122(
            repository=repository,
            llm=llm,
            model=settings.ollama_model,
            # Thinking mode is versioned together with the active analysis profile
            # so idempotent results remain reproducible.
            think=ANALYSIS_THINK,
            temperature=settings.analysis_temperature,
            min_samples=settings.analysis_min_samples,
        )
        run = WVCAnalysisPolicy(repository, service).run_window(
            source_id=args.source_id,
            window_start=window_start,
            window_end=window_end,
        )
    finally:
        database.dispose()

    print(json.dumps(run.as_dict(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
