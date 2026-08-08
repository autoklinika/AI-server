from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class OllamaConfig:
    base_url: str
    model: str


class OllamaClient:
    """Stage 1 boundary for future Ollama integration.

    This client intentionally has no control-system API. Future methods may only
    request analysis/recommendations and return advisory results.
    """

    def __init__(self, config: OllamaConfig) -> None:
        self.config = config

    async def analyze(self, context: dict) -> dict:
        raise NotImplementedError("Ollama analysis is not enabled in AI Bridge Stage 1")
