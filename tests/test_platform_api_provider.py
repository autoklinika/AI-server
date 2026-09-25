from copy import deepcopy
from dataclasses import replace
import json

import httpx
import pytest

from ai_bridge.providers.contracts import LLMProvider, LLMRequest
from ai_bridge.providers.platform_api import PlatformAPIProvider
from ai_bridge.settings import Settings


REQUEST = LLMRequest(request_id="req-1", capability="structured-generation",
    messages=[{"role": "user", "content": "Hypothesis"}], response_schema={"type": "object"},
    temperature=0.25, model_hint="private-backend", provider_hint="private-provider",
    context={"domain": "ecu-repair", "context_ref": "abc", "session_id": "session-1",
             "actor_id": "op", "case_id": "case-1", "current_view": "signals",
             "context_hash": "private", "request_id": "wrong"})
RESPONSE = dict(schema_version=1, request_id="req-1", state="completed", content='{"statement":"Maybe"}',
    finish_reason="stop", usage=dict(input_tokens=12, output_tokens=7),
    execution=dict(provider="ollama-local", model="reasoning-main", node="node-1",
                   queue_wait_ms=2.5, duration_ms=123.25))


def provider(handler, **settings):
    return PlatformAPIProvider(Settings(gateway_url="http://gateway.test/", **settings),
                               transport=httpx.MockTransport(handler))


@pytest.mark.parametrize("token", [None, "a-secret-token-long-enough"])
def test_wire_and_public_response(token):
    def handle(request):
        assert str(request.url) == "http://gateway.test/api/v1/ai"
        assert request.method == "POST"
        assert request.headers["X-Request-Id"] == REQUEST.request_id
        assert request.headers.get("Authorization") == ("Bearer " + token if token else None)
        payload = json.loads(request.content)
        assert payload == dict(schema_version=1, capability=REQUEST.capability, model="reasoning-main",
            context={**{k: REQUEST.context[k] for k in PlatformAPIProvider.context_fields}, "request_id": "req-1"},
            priority_class="interactive", messages=REQUEST.messages, response_schema=REQUEST.response_schema,
            temperature=0.25, timeout_seconds=600.0)
        assert all(0 < n <= 600 for n in request.extensions["timeout"].values())
        return httpx.Response(200, json={**RESPONSE, "private": "hidden"})
    adapter = provider(handle, platform_api_token=token, gateway_upstream_timeout_seconds=900)
    assert isinstance(adapter, LLMProvider)
    result = adapter.generate(REQUEST)
    assert result.content == RESPONSE["content"] and result.request_id == "req-1"
    assert (result.usage.input_tokens, result.usage.output_tokens) == (12, 7)
    assert result.execution.provider == "ollama-local"
    assert result.execution.model == "reasoning-main" and result.execution.node == "node-1"
    assert result.execution.duration_ns == 123250000 and result.execution.queue_wait_ms == 2.5
    assert result.provider_metadata == {} and result.tool_calls == ()


@pytest.mark.parametrize("mutation", ["id", "missing", "private-model", "negative", "tokens", "state", "version"])
def test_malformed_envelope(mutation):
    data = deepcopy(RESPONSE)
    if mutation == "id": data["request_id"] = "different"
    if mutation == "missing": del data["execution"]
    if mutation == "private-model": data["execution"]["model"] = "raw-backend"
    if mutation == "negative": data["execution"]["duration_ms"] = -1
    if mutation == "tokens": data["usage"]["input_tokens"] = "12"
    if mutation == "state": data["state"] = "failed"
    if mutation == "version": data["schema_version"] = 2
    with pytest.raises(ValueError, match="request_id mismatch" if mutation == "id" else None):
        provider(lambda _: httpx.Response(200, json=data)).generate(REQUEST)


@pytest.mark.parametrize("status", [302, 401, 429, 500, 503])
def test_http_failure(status):
    with pytest.raises(httpx.HTTPStatusError):
        provider(lambda _: httpx.Response(status, json={"error": "failed"})).generate(REQUEST)


def test_invalid_json_and_network_failure():
    with pytest.raises(ValueError):
        provider(lambda _: httpx.Response(200, text="not-json")).generate(REQUEST)
    def fail(request):
        raise httpx.ReadTimeout("deadline", request=request)
    with pytest.raises(httpx.ReadTimeout):
        provider(fail).generate(REQUEST)


@pytest.mark.parametrize("changes", [dict(tools=[{"name": "send"}]),
    dict(messages=[{"role": "assistant", "content": "x", "tool_calls": [{"name": "send"}]}]),
    dict(messages=[{"role": "tool", "content": "x"}]), dict(response_schema=None),
    dict(capability="embeddings"), dict(context={"session_id": "unsafe/id"})])
def test_rejected_before_http(changes):
    def unexpected(_):
        pytest.fail("invalid input reached HTTP")
    with pytest.raises(ValueError):
        provider(unexpected).generate(replace(REQUEST, **changes))


@pytest.mark.parametrize("capability", ["chat", "reasoning"])
def test_other_logical_capabilities_and_priority(capability):
    def handle(request):
        assert json.loads(request.content)["priority_class"] == "background"
        return httpx.Response(200, json=RESPONSE)
    adapter = PlatformAPIProvider(Settings(), priority_class="background", transport=httpx.MockTransport(handle))
    adapter.generate(replace(REQUEST, capability=capability, response_schema=None))
    with pytest.raises(NotImplementedError):
        adapter.stream(REQUEST)
    with pytest.raises(ValueError):
        PlatformAPIProvider(Settings(), priority_class="invalid")


@pytest.mark.parametrize("data,status,expected", [
    (dict(schema_version=1, readiness=True), 200, "ready"),
    (dict(schema_version=1, readiness=False), 200, "degraded"),
    ({}, 200, "unavailable"), ({}, 503, "unavailable")])
def test_health_and_description(data, status, expected):
    def handle(request):
        assert request.url.path == "/api/v1/health" and request.method == "GET"
        assert request.headers["Authorization"] == "Bearer a-secret-token-long-enough"
        assert all(0 < n <= 2 for n in request.extensions["timeout"].values())
        return httpx.Response(status, json=data)
    adapter = provider(handle, platform_api_token="a-secret-token-long-enough")
    assert adapter.health().status == expected
    description = adapter.describe()
    assert description.provider_id == "platform-api-v1"
    assert description.models == ("reasoning-main",) and description.status == expected
    assert description.capabilities == ("chat", "reasoning", "structured-generation")
