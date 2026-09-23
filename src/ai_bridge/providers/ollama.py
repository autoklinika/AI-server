from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator

from ai_bridge.ollama.client import OllamaClient, compact_schema_for_ollama
from ai_bridge.providers.contracts import (
    EmbeddingRequest,
    EmbeddingResult,
    EmbeddingUsage,
    EmbeddingVector,
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
    node_id: str | None = None

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
        node_id: str | None = None,
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


@dataclass(frozen=True)
class OllamaEmbeddingAdapter:
    """EmbeddingProvider adapter for the scheduled Ollama-compatible Gateway."""

    client: OllamaClient
    default_model: str
    provider_id: str = "embedding-local"
    node_id: str | None = None
    query_instruction: str | None = None
    keep_alive: str = "5m"

    @classmethod
    def from_endpoint(
        cls,
        *,
        base_url: str,
        default_model: str,
        timeout_seconds: float = 300.0,
        availability_timeout_seconds: float = 2.0,
        request_source: str | None = "knowledge-embedding",
        request_priority: int | None = None,
        provider_id: str = "embedding-local",
        node_id: str | None = None,
        query_instruction: str | None = None,
        keep_alive: str = "5m",
    ) -> "OllamaEmbeddingAdapter":
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
            query_instruction=query_instruction,
            keep_alive=keep_alive,
        )

    def _inputs(self, request: EmbeddingRequest) -> tuple[str, ...]:
        if not request.inputs or any(not value.strip() for value in request.inputs):
            raise ValueError("embedding inputs must be non-empty strings")
        role = request.context.get("embedding_role")
        if role not in (None, "query", "document"):
            raise ValueError("embedding_role must be query or document")
        if role == "query" and self.query_instruction:
            return tuple(
                f"Instruct: {self.query_instruction}\nQuery: {value}"
                for value in request.inputs
            )
        return request.inputs

    def embed(self, request: EmbeddingRequest) -> EmbeddingResult:
        model = request.model_hint or self.default_model
        result = self.client.embed(
            model=model,
            inputs=self._inputs(request),
            keep_alive=self.keep_alive,
        )
        if not result.embeddings:
            raise RuntimeError("embedding provider returned no vectors")
        dimensions = len(result.embeddings[0])
        if request.dimensions_hint is not None and dimensions != request.dimensions_hint:
            raise RuntimeError("embedding provider returned unexpected dimensions")
        return EmbeddingResult(
            request_id=request.request_id,
            vectors=tuple(
                EmbeddingVector(index=index, values=values)
                for index, values in enumerate(result.embeddings)
            ),
            provider=self.provider_id,
            model=result.model,
            dimensions=dimensions,
            usage=EmbeddingUsage(input_tokens=result.prompt_eval_count),
            duration_ms=(
                None
                if result.total_duration_ns is None
                else result.total_duration_ns / 1_000_000.0
            ),
        )

    def health(self) -> ProviderHealth:
        if self.client.is_available():
            return ProviderHealth(status="ready")
        return ProviderHealth(status="unavailable", detail="Embedding endpoint is unreachable")

    def describe(self) -> ProviderDescriptor:
        health = self.health()
        return ProviderDescriptor(
            provider_id=self.provider_id,
            provider_type="embedding",
            node_id=self.node_id,
            capabilities=("embeddings",),
            models=(self.default_model,),
            status=health.status,
            metadata={
                "query_instruction": self.query_instruction is not None,
            },
        )
