from __future__ import annotations

from functools import lru_cache

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

    # Ollama remains the inference backend. The AI Gateway is a local admission
    # layer in front of it and must therefore use this direct upstream URL.
    ollama_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "qwen3.6:35b"
    ollama_analysis_timeout_seconds: float = Field(default=300.0, gt=0.0)

    # Central inference gateway. It binds to localhost by default because both
    # Hermes and the ventilation analysis runner live on the AI Server.
    gateway_host: str = "127.0.0.1"
    gateway_port: int = Field(default=11435, ge=1, le=65535)
    gateway_url: str = "http://127.0.0.1:11435"
    gateway_max_concurrency: int = Field(default=1, ge=1, le=16)
    gateway_max_queue_size: int = Field(default=128, ge=1, le=10_000)
    gateway_connect_timeout_seconds: float = Field(default=5.0, gt=0.0)
    gateway_upstream_timeout_seconds: float = Field(default=600.0, gt=0.0)
    gateway_health_timeout_seconds: float = Field(default=2.0, gt=0.0)

    # Lower numeric value means higher priority. These defaults leave wide gaps
    # so future workloads can be inserted without renumbering existing classes.
    gateway_priority_ventilation: int = Field(default=10, ge=-1000, le=1000)
    gateway_priority_interactive: int = Field(default=50, ge=-1000, le=1000)
    gateway_priority_normal: int = Field(default=100, ge=-1000, le=1000)
    gateway_priority_background: int = Field(default=200, ge=-1000, le=1000)

    # Safe rollout switch: production analysis continues to talk directly to
    # Ollama until the local gateway has been deployed and validated.
    analysis_use_gateway: bool = False

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
