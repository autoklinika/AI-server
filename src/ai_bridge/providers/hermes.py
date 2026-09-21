from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Iterable, Iterator

import httpx

from ai_bridge.providers.contracts import (
    AgentEvent,
    AgentProvider,
    AgentTurnRequest,
    AgentTurnResult,
    AgentUsage,
    ProviderDescriptor,
    ProviderHealth,
)


@dataclass(frozen=True)
class HermesAdapter:
    """AgentProvider adapter for the local Hermes API Server.

    Stage C uses Hermes' documented HTTP boundary instead of importing Hermes
    Python internals. Existing Telegram/Discord runtime stays untouched.
    """

    base_url: str
    api_key: str
    model_name: str = "hermes-agent"
    timeout_seconds: float = 600.0
    health_timeout_seconds: float = 2.0
    provider_id: str = "hermes-local"
    node_id: str = "ai-node-01"

    def __post_init__(self) -> None:
        if not self.base_url.strip():
            raise ValueError("HermesAdapter base_url must not be empty")
        if not self.api_key.strip():
            raise ValueError("HermesAdapter api_key must not be empty")
        if not self.model_name.strip():
            raise ValueError("HermesAdapter model_name must not be empty")

    @property
    def _root(self) -> str:
        return self.base_url.rstrip("/")

    def _headers(self, request: AgentTurnRequest | None = None) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
        }
        if request is not None and request.session_id:
            headers["X-Hermes-Session-Id"] = request.session_id
        return headers

    @staticmethod
    def _validate_request(request: AgentTurnRequest) -> None:
        if not request.request_id.strip():
            raise ValueError("AgentTurnRequest.request_id must not be empty")
        if not request.session_id.strip():
            raise ValueError("AgentTurnRequest.session_id must not be empty")
        if not request.message.strip():
            raise ValueError("AgentTurnRequest.message must not be empty")
        if request.allowed_toolsets:
            raise NotImplementedError(
                "Hermes API Server does not expose per-request toolset narrowing "
                "through the Stage C adapter; configure toolsets for platform api_server."
            )

    def _payload(self, request: AgentTurnRequest, *, stream: bool) -> dict:
        return {
            "model": self.model_name,
            "messages": [{"role": "user", "content": request.message}],
            "stream": stream,
        }

    def run_turn(self, request: AgentTurnRequest) -> AgentTurnResult:
        self._validate_request(request)
        try:
            response = httpx.post(
                f"{self._root}/v1/chat/completions",
                headers={
                    **self._headers(request),
                    "Content-Type": "application/json",
                },
                json=self._payload(request, stream=False),
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text[:2000]
            raise RuntimeError(
                f"Hermes returned HTTP {exc.response.status_code}: {detail}"
            ) from exc
        except httpx.HTTPError as exc:
            raise RuntimeError(f"Hermes unavailable: {exc}") from exc

        data = response.json()
        choices = data.get("choices")
        if not isinstance(choices, list) or not choices:
            raise RuntimeError("Hermes response does not contain choices")
        choice = choices[0]
        if not isinstance(choice, dict):
            raise RuntimeError("Hermes response choice is invalid")
        message = choice.get("message")
        if not isinstance(message, dict):
            raise RuntimeError("Hermes response does not contain message object")
        content = message.get("content")
        if not isinstance(content, str):
            raise RuntimeError("Hermes response does not contain assistant content")

        usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
        response_session = response.headers.get("X-Hermes-Session-Id") or request.session_id
        metadata = {}
        if isinstance(data.get("hermes"), dict):
            metadata["hermes"] = data["hermes"]
        if isinstance(data.get("id"), str):
            metadata["response_id"] = data["id"]

        return AgentTurnResult(
            request_id=request.request_id,
            session_id=response_session,
            content=content,
            finish_reason=str(choice.get("finish_reason") or "stop"),
            usage=AgentUsage(
                input_tokens=_optional_int(usage.get("prompt_tokens")),
                output_tokens=_optional_int(usage.get("completion_tokens")),
            ),
            provider=self.provider_id,
            model=str(data.get("model") or self.model_name),
            provider_metadata=metadata,
        )

    def stream_turn(self, request: AgentTurnRequest) -> Iterator[AgentEvent]:
        self._validate_request(request)
        try:
            with httpx.stream(
                "POST",
                f"{self._root}/v1/chat/completions",
                headers={
                    **self._headers(request),
                    "Accept": "text/event-stream",
                    "Content-Type": "application/json",
                },
                json=self._payload(request, stream=True),
                timeout=self.timeout_seconds,
            ) as response:
                response.raise_for_status()
                response_session = (
                    response.headers.get("X-Hermes-Session-Id") or request.session_id
                )
                yield AgentEvent(
                    request_id=request.request_id,
                    session_id=response_session,
                    type="started",
                    data={"provider": self.provider_id},
                )
                completed = False
                for event_name, payload in _iter_sse_events(response.iter_lines()):
                    if payload == "[DONE]":
                        if not completed:
                            completed = True
                            yield AgentEvent(
                                request_id=request.request_id,
                                session_id=response_session,
                                type="completed",
                            )
                        break

                    try:
                        data = json.loads(payload)
                    except json.JSONDecodeError as exc:
                        raise RuntimeError("Hermes SSE contained invalid JSON") from exc
                    if not isinstance(data, dict):
                        continue

                    if event_name == "hermes.tool.progress":
                        status = str(data.get("status") or "")
                        if status == "running":
                            event_type = "tool_started"
                        elif status == "completed":
                            event_type = "tool_finished"
                        else:
                            continue
                        yield AgentEvent(
                            request_id=request.request_id,
                            session_id=response_session,
                            type=event_type,
                            data=data,
                        )
                        continue

                    choices = data.get("choices")
                    if not isinstance(choices, list) or not choices:
                        continue
                    choice = choices[0]
                    if not isinstance(choice, dict):
                        continue
                    delta = choice.get("delta")
                    if isinstance(delta, dict):
                        content = delta.get("content")
                        if isinstance(content, str) and content:
                            yield AgentEvent(
                                request_id=request.request_id,
                                session_id=response_session,
                                type="token/chunk",
                                data={"content": content},
                            )
                    finish_reason = choice.get("finish_reason")
                    if finish_reason is not None and not completed:
                        completed = True
                        yield AgentEvent(
                            request_id=request.request_id,
                            session_id=response_session,
                            type="completed",
                            data={"finish_reason": str(finish_reason)},
                        )
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text[:2000]
            raise RuntimeError(
                f"Hermes returned HTTP {exc.response.status_code}: {detail}"
            ) from exc
        except httpx.HTTPError as exc:
            raise RuntimeError(f"Hermes unavailable: {exc}") from exc

    def health(self) -> ProviderHealth:
        try:
            response = httpx.get(
                f"{self._root}/health",
                headers=self._headers(),
                timeout=self.health_timeout_seconds,
            )
            if response.is_success:
                return ProviderHealth(status="ready")
            return ProviderHealth(
                status="degraded",
                detail=f"Hermes health returned HTTP {response.status_code}",
            )
        except httpx.HTTPError as exc:
            return ProviderHealth(status="unavailable", detail=str(exc))

    def describe(self) -> ProviderDescriptor:
        health = self.health()
        return ProviderDescriptor(
            provider_id=self.provider_id,
            provider_type="agent",
            node_id=self.node_id,
            capabilities=("reasoning", "tools", "streaming"),
            models=(self.model_name,),
            status=health.status,
            metadata={
                "transport": "http",
                "api": "openai-chat-completions",
                "session_continuity_header": "X-Hermes-Session-Id",
                "toolsets": "provider-configured",
            },
        )


def _optional_int(value: object) -> int | None:
    return value if isinstance(value, int) else None


def _iter_sse_events(lines: Iterable[str]) -> Iterator[tuple[str | None, str]]:
    event_name: str | None = None
    data_lines: list[str] = []

    def flush() -> tuple[str | None, str] | None:
        nonlocal event_name, data_lines
        if not data_lines:
            event_name = None
            return None
        item = (event_name, "\n".join(data_lines))
        event_name = None
        data_lines = []
        return item

    for raw in lines:
        line = raw.rstrip("\r")
        if not line:
            item = flush()
            if item is not None:
                yield item
            continue
        if line.startswith(":"):
            continue
        if line.startswith("event:"):
            event_name = line[6:].strip() or None
            continue
        if line.startswith("data:"):
            data_lines.append(line[5:].lstrip())
            continue

    item = flush()
    if item is not None:
        yield item
