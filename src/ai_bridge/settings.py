from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="AI_BRIDGE_",
        env_file=".env",
        extra="ignore",
    )

    host: str = "0.0.0.0"
    port: int = Field(default=8080, ge=1, le=65535)
    log_level: str = "INFO"

    # SQLite is a development-safe default. Production targets PostgreSQL
    # through AI_BRIDGE_DATABASE_URL without changing application code.
    database_url: str = "sqlite+pysqlite:///./data/ai_bridge.sqlite3"

    # The telemetry archive is deliberately behind a logical backend boundary.
    # Stage 4 implements only the existing SQL backend. A future NAS backend is
    # added as a separate implementation; selecting an unsupported backend must
    # fail configuration rather than silently pretending that NAS is active.
    ventilation_storage_backend: Literal["sql"] = "sql"
    ventilation_storage_location_label: str = Field(default="AI Server", min_length=1, max_length=128)

    ollama_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "qwen3.6:35b"
    ollama_analysis_timeout_seconds: float = Field(default=300.0, gt=0.0)

    analysis_window_minutes: int = Field(default=15, ge=1, le=60)
    analysis_min_samples: int = Field(default=120, ge=1)
    analysis_temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    ventilation_source_id: str = "workshop-ventilation-cm5-01"

    telemetry_max_body_bytes: int = Field(default=1_048_576, ge=1024)

    @field_validator("analysis_window_minutes")
    @classmethod
    def validate_analysis_window_minutes(cls, value: int) -> int:
        if 60 % value != 0:
            raise ValueError("analysis_window_minutes must be a divisor of 60")
        return value


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
