from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterator, Literal, Protocol, runtime_checkable


ProviderStatus = Literal["ready", "degraded", "unavailable"]


@dataclass(frozen=True)
class ProviderHealth:
    status: ProviderStatus
    detail: str | None = None


@dataclass(frozen=True)
class ProviderDescriptor:
    provider_id: str
    provider_type: str
    node_id: str | None
    capabilities: tuple[str, ...]
    models: tuple[str, ...]
    status: ProviderStatus
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class LLMRequest:
    request_id: str
    capability: str
    messages: list[dict[str, str]]
    response_schema: dict[str, Any] | None = None
    tools: list[dict[str, Any]] = field(default_factory=list)
    temperature: float = 0.0
    reasoning_enabled: bool = False
    context: dict[str, Any] = field(default_factory=dict)
    provider_hint: str | None = None
    model_hint: str | None = None


@dataclass(frozen=True)
class LLMUsage:
    input_tokens: int | None = None
    output_tokens: int | None = None


@dataclass(frozen=True)
class LLMExecution:
    provider: str
    model: str
    node: str | None = None
    queue_wait_ms: float | None = None
    duration_ns: int | None = None

    @property
    def duration_ms(self) -> float | None:
        if self.duration_ns is None:
            return None
        return self.duration_ns / 1_000_000.0


@dataclass(frozen=True)
class LLMResponse:
    request_id: str
    content: str
    tool_calls: tuple[dict[str, Any], ...] = ()
    finish_reason: str = "stop"
    usage: LLMUsage = field(default_factory=LLMUsage)
    execution: LLMExecution = field(
        default_factory=lambda: LLMExecution(provider="unknown", model="unknown")
    )
    provider_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class LLMChunk:
    request_id: str
    content: str
    done: bool = False


@runtime_checkable
class LLMProvider(Protocol):
    def generate(self, request: LLMRequest) -> LLMResponse:
        ...

    def stream(self, request: LLMRequest) -> Iterator[LLMChunk]:
        ...

    def health(self) -> ProviderHealth:
        ...

    def describe(self) -> ProviderDescriptor:
        ...


@dataclass(frozen=True)
class EmbeddingRequest:
    request_id: str
    inputs: tuple[str, ...]
    capability: Literal["embeddings"] = "embeddings"
    model_hint: str | None = None
    dimensions_hint: int | None = None
    context: dict[str, Any] = field(default_factory=dict)
    provider_hint: str | None = None


@dataclass(frozen=True)
class EmbeddingVector:
    index: int
    values: tuple[float, ...]


@dataclass(frozen=True)
class EmbeddingUsage:
    input_tokens: int | None = None


@dataclass(frozen=True)
class EmbeddingResult:
    request_id: str
    vectors: tuple[EmbeddingVector, ...]
    provider: str
    model: str
    dimensions: int
    usage: EmbeddingUsage = field(default_factory=EmbeddingUsage)
    duration_ms: float | None = None
    provider_metadata: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class EmbeddingProvider(Protocol):
    def embed(self, request: EmbeddingRequest) -> EmbeddingResult:
        ...

    def health(self) -> ProviderHealth:
        ...

    def describe(self) -> ProviderDescriptor:
        ...


AgentEventType = Literal[
    "queued",
    "started",
    "token/chunk",
    "tool_started",
    "tool_finished",
    "artifact_created",
    "completed",
    "failed",
    "cancelled",
]


@dataclass(frozen=True)
class AgentTurnRequest:
    request_id: str
    session_id: str
    message: str
    context: dict[str, Any] = field(default_factory=dict)
    allowed_toolsets: tuple[str, ...] = ()
    capability: str = "reasoning"


@dataclass(frozen=True)
class AgentUsage:
    input_tokens: int | None = None
    output_tokens: int | None = None


@dataclass(frozen=True)
class AgentTurnResult:
    request_id: str
    session_id: str
    content: str
    finish_reason: str = "stop"
    usage: AgentUsage = field(default_factory=AgentUsage)
    provider: str = "unknown"
    model: str | None = None
    provider_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AgentEvent:
    request_id: str
    session_id: str
    type: AgentEventType
    data: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class AgentProvider(Protocol):
    def run_turn(self, request: AgentTurnRequest) -> AgentTurnResult:
        ...

    def stream_turn(self, request: AgentTurnRequest) -> Iterator[AgentEvent]:
        ...

    def health(self) -> ProviderHealth:
        ...

    def describe(self) -> ProviderDescriptor:
        ...


MediaCapability = Literal[
    "image-generation",
    "image-edit",
    "video-generation",
]


@dataclass(frozen=True)
class MediaGenerationRequest:
    request_id: str
    capability: MediaCapability
    profile: str
    prompt: str
    output_dir: str
    timeout_seconds: float = 3600.0
    input_artifacts: tuple[str, ...] = ()
    parameters: dict[str, Any] = field(default_factory=dict)
    context: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MediaArtifact:
    uri: str
    media_type: str
    size_bytes: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MediaGenerationResult:
    request_id: str
    capability: MediaCapability
    profile: str
    artifacts: tuple[MediaArtifact, ...]
    provider: str
    duration_ms: float | None = None
    provider_metadata: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class MediaGenerationProvider(Protocol):
    def generate(self, request: MediaGenerationRequest) -> MediaGenerationResult:
        ...

    def health(self) -> ProviderHealth:
        ...

    def describe(self) -> ProviderDescriptor:
        ...


KnowledgeQueryMode = Literal[
    "exact",
    "keyword",
    "semantic",
    "hybrid",
    "auto",
]


@dataclass(frozen=True)
class KnowledgeSource:
    type: str
    uri: str
    title: str | None = None


@dataclass(frozen=True)
class KnowledgeQuery:
    request_id: str
    domain: str
    query: str
    mode: KnowledgeQueryMode = "auto"
    namespaces: tuple[str, ...] = ()
    source_types: tuple[str, ...] = ()
    filters: dict[str, Any] = field(default_factory=dict)
    limit: int = 10
    query_embedding: tuple[float, ...] | None = None
    context: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class KnowledgeResult:
    result_id: str
    text: str
    source: KnowledgeSource
    score: float
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class KnowledgeSearchResult:
    request_id: str
    results: tuple[KnowledgeResult, ...]
    backend: str
    duration_ms: float | None = None
    backend_metadata: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class KnowledgeBackend(Protocol):
    def search(self, query: KnowledgeQuery) -> KnowledgeSearchResult:
        ...

    def health(self) -> ProviderHealth:
        ...

    def describe(self) -> ProviderDescriptor:
        ...
