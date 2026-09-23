"""Domain-independent health response, preserving the existing wire contract."""
from typing import Literal
from pydantic import BaseModel, ConfigDict


class StrictHealthModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class HealthComponents(StrictHealthModel):
    database: Literal["ok", "unavailable"]
    ollama: Literal["not_checked"] = "not_checked"


class HealthResponse(StrictHealthModel):
    status: Literal["ok", "unavailable"]
    service: Literal["ai-bridge"] = "ai-bridge"
    version: str
    control_commands_supported: Literal[False] = False
    components: HealthComponents
