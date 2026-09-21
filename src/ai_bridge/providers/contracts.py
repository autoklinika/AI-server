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
