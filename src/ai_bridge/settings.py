from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from ai_bridge.providers.accelerators import AcceleratorRegistry
from ai_bridge.providers.registry import DescriptorRegistry


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="AI_BRIDGE_",
        env_file=".env",
        extra="ignore",
    )

    host: str = "0.0.0.0"
    port: int = Field(default=8080, ge=1, le=65535)
    log_level: str = "INFO"
    node_id: str = Field(default="ai-node-01", min_length=1, max_length=128)

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
    platform_api_token: SecretStr | None = Field(default=None, min_length=16)

    gateway_host: str = "127.0.0.1"
    gateway_port: int = Field(default=11435, ge=1, le=65535)
    gateway_url: str = "http://127.0.0.1:11435"
    gateway_comfy_url: str = "http://127.0.0.1:8188"
    gateway_comfy_idle_reserve_bytes: int = Field(default=0, ge=0, le=67108864)
    gateway_gpu_transition_timeout: float = Field(default=90.0, gt=0.0)
    gateway_gpu_marker: Path = Field(default_factory=lambda: Path.home() / ".local/state/ai-platform/gpu-residency.blocked")
    gateway_max_concurrency: int = Field(default=1, ge=1, le=16)
    gateway_max_queue_size: int = Field(default=128, ge=1, le=10_000)
    gateway_connect_timeout_seconds: float = Field(default=5.0, gt=0.0)
    gateway_upstream_timeout_seconds: float = Field(default=600.0, gt=0.0)
    gateway_health_timeout_seconds: float = Field(default=2.0, gt=0.0)
    # Optional JSON static inventory. None derives the D.3 baseline from node_id.
    # Gateway validates existing single-node bindings before creating clients.
    gateway_registry: DescriptorRegistry | None = None
    # Stage N0 static accelerator inventory. It is descriptive only: live
    # routing remains on the existing shared local resource pool until N1.
    gateway_accelerator_registry: AcceleratorRegistry | None = None

    # External Resource Manager leases let FLUX/LTX and other non-HTTP workers
    # reserve the same admission slot as Ollama. Idle leases expire so a crashed
    # worker cannot block the server indefinitely; active work is never reaped.
    gateway_external_lease_ttl_seconds: float = Field(
        default=45.0,
        ge=10.0,
        le=600.0,
    )

    # Legacy endpoint defaults; lower numeric value means higher priority.
    # D.1 explicit semantic classes use the fixed mapping in gateway.priority.
    gateway_priority_ventilation: int = Field(default=10, ge=-1000, le=1000)
    gateway_priority_interactive: int = Field(default=50, ge=-1000, le=1000)
    gateway_priority_normal: int = Field(default=100, ge=-1000, le=1000)
    gateway_priority_background: int = Field(default=200, ge=-1000, le=1000)

    # Gateway is the production-default admission path. Setting this to false
    # is an explicit recovery/debug compatibility mode that bypasses scheduling.
    analysis_use_gateway: bool = True

    # Knowledge Service physical index defaults. These are internal deployment
    # choices, not part of the public Knowledge Service client contract.
    knowledge_qdrant_url: str = "http://127.0.0.1:6333"
    knowledge_qdrant_collection: str = "knowledge_dense_bge_m3_1024_v1"
    knowledge_embedding_model: str = "bge-m3"
    knowledge_embedding_dimensions: int = Field(default=1024, ge=1, le=16384)
    knowledge_chunk_max_chars: int = Field(default=2400, ge=256, le=20000)
    knowledge_chunk_profile: str = "md-heading-2400-v1"
    knowledge_pdf_chunk_profile: str = "pdf-page-2400-v1"
    knowledge_index_profile: str = "dense-bge-m3-1024-cosine-v1"
    knowledge_object_store_dir: Path = Path("/srv/ai-data/knowledge/canonical/objects")
    knowledge_pdf_tesseract: Path = Path("/srv/ai-data/tools/tesseract-portable/root/usr/bin/tesseract")
    knowledge_pdf_tessdata_dir: Path = Path("/srv/ai-data/tools/tesseract-portable/root/usr/share/tesseract-ocr/5/tessdata")
    knowledge_pdf_tesseract_lib_dir: Path = Path("/srv/ai-data/tools/tesseract-portable/root/usr/lib/x86_64-linux-gnu")
    knowledge_pdf_ocr_languages: str = "eng+pol"
    knowledge_pdf_ocr_min_alnum: int = Field(default=80, ge=0, le=10000)
    knowledge_rag_max_sources: int = Field(default=8, ge=1, le=20)
    knowledge_rag_context_max_chars: int = Field(default=24000, ge=2000, le=100000)

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
