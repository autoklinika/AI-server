from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from ai_bridge.providers.contracts import AgentProvider, AgentTurnRequest
from ai_bridge.providers.hermes import HermesAdapter, _iter_sse_events


def _request(*, allowed_toolsets: tuple[str, ...] = ()) -> AgentTurnRequest:
    return AgentTurnRequest(
        request_id="req-agent-stage-c",
        session_id="session-stage-c",
        message="Sprawdź status.",
        context={"domain": "shared"},
        allowed_toolsets=allowed_toolsets,
        capability="reasoning",
    )


def _adapter() -> HermesAdapter:
    return HermesAdapter(
        base_url="http://127.0.0.1:8642",
        api_key="test-secret",
        model_name="hermes-agent",
    )


def test_hermes_adapter_satisfies_agent_provider_runtime_contract() -> None:
    assert isinstance(_adapter(), AgentProvider)


def test_hermes_adapter_requires_secret_and_endpoint() -> None:
    with pytest.raises(ValueError):
        HermesAdapter(base_url="", api_key="secret")
    with pytest.raises(ValueError):
        HermesAdapter(base_url="http://127.0.0.1:8642", api_key="")


def test_hermes_adapter_maps_turn_to_documented_api_boundary(monkeypatch) -> None:
    captured: dict[str, Any] = {}

    def fake_post(url: str, *, headers: dict, json: dict, timeout: float):
        captured.update(
            {
                "url": url,
                "headers": headers,
                "json": json,
                "timeout": timeout,
            }
        )
        return httpx.Response(
            200,
            headers={"X-Hermes-Session-Id": "session-stage-c"},
            json={
                "id": "chatcmpl-stage-c",
                "object": "chat.completion",
                "model": "hermes-agent",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "Gotowe."},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 123,
                    "completion_tokens": 45,
                    "total_tokens": 168,
                },
            },
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(httpx, "post", fake_post)

    result = _adapter().run_turn(_request())

    assert captured["url"] == "http://127.0.0.1:8642/v1/chat/completions"
    assert captured["headers"]["Authorization"] == "Bearer test-secret"
    assert captured["headers"]["X-Hermes-Session-Id"] == "session-stage-c"
    assert captured["json"] == {
        "model": "hermes-agent",
        "messages": [{"role": "user", "content": "Sprawdź status."}],
        "stream": False,
    }
    assert result.request_id == "req-agent-stage-c"
    assert result.session_id == "session-stage-c"
    assert result.content == "Gotowe."
    assert result.finish_reason == "stop"
    assert result.usage.input_tokens == 123
    assert result.usage.output_tokens == 45
    assert result.provider == "hermes-local"
    assert result.model == "hermes-agent"
    assert result.provider_metadata["response_id"] == "chatcmpl-stage-c"


def test_hermes_adapter_does_not_fake_per_request_toolset_enforcement() -> None:
    with pytest.raises(NotImplementedError, match="toolset"):
        _adapter().run_turn(_request(allowed_toolsets=("web",)))


def test_hermes_adapter_health_and_descriptor_contract(monkeypatch) -> None:
    def ready_get(url: str, *, headers: dict, timeout: float):
        assert url == "http://127.0.0.1:8642/health"
        assert headers["Authorization"] == "Bearer test-secret"
        return httpx.Response(
            200,
            json={"status": "ok"},
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr(httpx, "get", ready_get)
    adapter = _adapter()

    assert adapter.health().status == "ready"
    descriptor = adapter.describe()
    assert descriptor.provider_id == "hermes-local"
    assert descriptor.provider_type == "agent"
    assert descriptor.node_id == "ai-node-01"
    assert "reasoning" in descriptor.capabilities
    assert "tools" in descriptor.capabilities
    assert "streaming" in descriptor.capabilities
    assert descriptor.models == ("hermes-agent",)
    assert descriptor.metadata["session_continuity_header"] == "X-Hermes-Session-Id"
    assert descriptor.metadata["toolsets"] == "provider-configured"


def test_hermes_adapter_health_reports_unavailable(monkeypatch) -> None:
    def failing_get(*_args, **_kwargs):
        raise httpx.ConnectError("offline")

    monkeypatch.setattr(httpx, "get", failing_get)
    health = _adapter().health()
    assert health.status == "unavailable"
    assert "offline" in (health.detail or "")


def test_sse_parser_skips_keepalive_and_preserves_custom_event() -> None:
    lines = [
        ": keepalive",
        "",
        "event: hermes.tool.progress",
        'data: {"tool":"terminal","toolCallId":"call-1","status":"running"}',
        "",
        'data: {"choices":[{"delta":{"content":"OK"},"finish_reason":null}]}',
        "",
        "data: [DONE]",
        "",
    ]

    assert list(_iter_sse_events(lines)) == [
        (
            "hermes.tool.progress",
            '{"tool":"terminal","toolCallId":"call-1","status":"running"}',
        ),
        (
            None,
            '{"choices":[{"delta":{"content":"OK"},"finish_reason":null}]}',
        ),
        (None, "[DONE]"),
    ]


def test_hermes_adapter_normalizes_stream_events(monkeypatch) -> None:
    captured: dict[str, Any] = {}

    class FakeStreamResponse:
        headers = {"X-Hermes-Session-Id": "session-stage-c"}

        def raise_for_status(self) -> None:
            return None

        def iter_lines(self):
            yield ": keepalive"
            yield ""
            yield "event: hermes.tool.progress"
            yield 'data: {"tool":"terminal","toolCallId":"call-1","status":"running"}'
            yield ""
            yield 'data: {"choices":[{"delta":{"content":"O"},"finish_reason":null}]}'
            yield ""
            yield 'data: {"choices":[{"delta":{"content":"K"},"finish_reason":null}]}'
            yield ""
            yield "event: hermes.tool.progress"
            yield 'data: {"tool":"terminal","toolCallId":"call-1","status":"completed"}'
            yield ""
            yield 'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}'
            yield ""
            yield "data: [DONE]"
            yield ""

    class FakeStreamContext:
        def __enter__(self):
            return FakeStreamResponse()

        def __exit__(self, exc_type, exc, tb):
            return False

    def fake_stream(method: str, url: str, *, headers: dict, json: dict, timeout: float):
        captured.update(
            {
                "method": method,
                "url": url,
                "headers": headers,
                "json": json,
                "timeout": timeout,
            }
        )
        return FakeStreamContext()

    monkeypatch.setattr(httpx, "stream", fake_stream)

    events = list(_adapter().stream_turn(_request()))

    assert captured["method"] == "POST"
    assert captured["url"] == "http://127.0.0.1:8642/v1/chat/completions"
    assert captured["headers"]["Authorization"] == "Bearer test-secret"
    assert captured["headers"]["X-Hermes-Session-Id"] == "session-stage-c"
    assert captured["json"]["stream"] is True

    assert [event.type for event in events] == [
        "started",
        "tool_started",
        "token/chunk",
        "token/chunk",
        "tool_finished",
        "completed",
    ]
    assert events[1].data["tool"] == "terminal"
    assert events[2].data["content"] == "O"
    assert events[3].data["content"] == "K"
    assert events[-1].data["finish_reason"] == "stop"
