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
