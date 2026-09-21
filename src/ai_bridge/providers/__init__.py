"""Stable AI provider contracts and concrete adapters."""

from ai_bridge.providers.contracts import (
    LLMChunk,
    LLMExecution,
    LLMProvider,
    LLMRequest,
    LLMResponse,
    LLMUsage,
    ProviderDescriptor,
    ProviderHealth,
)
from ai_bridge.providers.ollama import OllamaAdapter

__all__ = [
    "LLMChunk",
    "LLMExecution",
    "LLMProvider",
    "LLMRequest",
    "LLMResponse",
    "LLMUsage",
    "OllamaAdapter",
    "ProviderDescriptor",
    "ProviderHealth",
]
