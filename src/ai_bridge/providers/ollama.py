from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator

from ai_bridge.ollama.client import OllamaClient, compact_schema_for_ollama
from ai_bridge.providers.contracts import (
    LLMChunk,
    LLMExecution,
    LLMRequest,
    LLMResponse,
    LLMUsage,
    ProviderDescriptor,
    ProviderHealth,
)


@dataclass(frozen=True)
class OllamaAdapter:
    """LLMProvider adapter for the existing Ollama/Ollama-compatible route.

    Stage C deliberately keeps the current model, AI Gateway route and scheduler
    headers unchanged. Product-specific schema compaction stays inside this adapter.
    """

    client: OllamaClient
    default_model: str
    provider_id: str = "ollama-local"
    node_id: str = "ai-node-01"

    @classmethod
    def from_endpoint(
        cls,
        *,
        base_url: str,
        default_model: str,
        timeout_seconds: float = 300.0,
        availability_timeout_seconds: float = 2.0,
        request_source: str | None = None,
        request_priority: int | None = None,
        provider_id: str = "ollama-local",
        node_id: str = "ai-node-01",
    ) -> "OllamaAdapter":
        return cls(
            client=OllamaClient(
                base_url=base_url,
                timeout_seconds=timeout_seconds,
                availability_timeout_seconds=availability_timeout_seconds,
                request_source=request_source,
                request_priority=request_priority,
            ),
            default_model=default_model,
            provider_id=provider_id,
            node_id=node_id,
        )

    def generate(self, request: LLMRequest) -> LLMResponse:
        if request.response_schema is None:
            raise ValueError(
                "OllamaAdapter Stage C requires response_schema for structured generation"
            )

        model = request.model_hint or self.default_model
        sampling_schema = compact_schema_for_ollama(request.response_schema)
        result = self.client.chat_structured(
            model=model,
            messages=request.messages,
            response_schema=sampling_schema,
            think=request.reasoning_enabled,
            temperature=request.temperature,
        )
        return LLMResponse(
            request_id=request.request_id,
            content=result.content,
            usage=LLMUsage(
                input_tokens=result.prompt_eval_count,
                output_tokens=result.eval_count,
            ),
            execution=LLMExecution(
                provider=self.provider_id,
                model=result.model,
                node=self.node_id,
                duration_ns=result.total_duration_ns,
            ),
        )

    def stream(self, request: LLMRequest) -> Iterator[LLMChunk]:
        raise NotImplementedError(
            "OllamaAdapter token streaming is not enabled in Stage C"
        )

    def health(self) -> ProviderHealth:
        if self.client.is_available():
            return ProviderHealth(status="ready")
        return ProviderHealth(status="unavailable", detail="Ollama endpoint is unreachable")

    def describe(self) -> ProviderDescriptor:
        health = self.health()
        return ProviderDescriptor(
            provider_id=self.provider_id,
            provider_type="llm",
            node_id=self.node_id,
            capabilities=("reasoning", "structured-generation"),
            models=(self.default_model,),
            status=health.status,
            metadata={
                "streaming": False,
                "structured_output": True,
            },
        )
