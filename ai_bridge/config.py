from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os


def _as_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    host: str
    port: int
    database_path: Path
    ollama_url: str
    ollama_model: str
    analysis_enabled: bool


def load_settings() -> Settings:
    return Settings(
        host=os.getenv("AI_BRIDGE_HOST", "0.0.0.0"),
        port=int(os.getenv("AI_BRIDGE_PORT", "8080")),
        database_path=Path(os.getenv("AI_BRIDGE_DB", "data/ai_bridge.sqlite3")),
        ollama_url=os.getenv("AI_BRIDGE_OLLAMA_URL", "http://127.0.0.1:11434"),
        ollama_model=os.getenv("AI_BRIDGE_OLLAMA_MODEL", "qwen3.6:35b"),
        analysis_enabled=_as_bool(os.getenv("AI_BRIDGE_ANALYSIS_ENABLED"), default=False),
    )
