"""Synchronous LLM port over the scheduled, public Platform API v1."""
from __future__ import annotations

import re
from typing import Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field

from .contracts import LLMExecution, LLMRequest, LLMResponse, LLMUsage, ProviderDescriptor, ProviderHealth


class _PublicModel(BaseModel):
    # Ignore extensions; never copy private/unknown fields to provider metadata.
    model_config = ConfigDict(strict=True, extra="ignore", allow_inf_nan=False)


class _Usage(_PublicModel):
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)


class _Execution(_PublicModel):
    provider: str = Field(min_length=1)
    model: Literal["reasoning-main"]
    node: str = Field(min_length=1)
    queue_wait_ms: float = Field(ge=0)
    duration_ms: float = Field(ge=0)


class _Response(_PublicModel):
    schema_version: Literal[1]
    request_id: str
    state: Literal["completed"]
    content: str
    finish_reason: str = Field(min_length=1)
    usage: _Usage
    execution: _Execution


class PlatformAPIProvider:
    capabilities = ("chat", "reasoning", "structured-generation")
    context_fields = ("domain", "actor_id", "session_id", "case_id", "current_view", "context_ref")

    def __init__(self, settings, *, priority_class="interactive", transport=None):
        if priority_class not in ("infrastructure", "interactive-high", "interactive", "normal", "background", "maintenance"):
            raise ValueError("unsupported Platform API priority class")
        self.url = settings.gateway_url.rstrip("/")
        self.priority_class = priority_class
        self.timeout_seconds = min(settings.gateway_upstream_timeout_seconds, 600.0)
        self.timeout = httpx.Timeout(self.timeout_seconds,
            connect=min(settings.gateway_connect_timeout_seconds, self.timeout_seconds))
        self.health_timeout = min(settings.gateway_health_timeout_seconds, 600.0)
        self.headers = {}
        if settings.platform_api_token is not None:
            self.headers["Authorization"] = "Bearer " + settings.platform_api_token.get_secret_value()
        self.transport = transport

    def _call(self, method, path, **kwargs):
        # Per-call ownership avoids an unclosed client in ASGI factory/module imports.
        with httpx.Client(headers=self.headers, timeout=self.timeout,
                          transport=self.transport, trust_env=False) as client:
            response = client.request(method, self.url + path, **kwargs)
            response.raise_for_status()
            return response.json()

    def generate(self, request: LLMRequest) -> LLMResponse:
        if request.capability not in self.capabilities:
            raise ValueError("unsupported Platform API capability")
        if request.tools or any(message.get("tool_calls") or message.get("role") == "tool" for message in request.messages):
            raise ValueError("Platform API v1 does not support tools or tool_calls")
        if request.capability == "structured-generation" and request.response_schema is None:
            raise ValueError("structured-generation requires response_schema")
        context = {key: request.context[key] for key in self.context_fields if request.context.get(key) is not None}
        context["request_id"] = request.request_id
        if any(not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", value) for value in context.values()):
            raise ValueError("invalid Platform API context ID")
        payload = dict(schema_version=1, capability=request.capability, model="reasoning-main",
            context=context, priority_class=self.priority_class, messages=request.messages,
            response_schema=request.response_schema, temperature=request.temperature,
            timeout_seconds=self.timeout_seconds)
        data = self._call("POST", "/api/v1/ai", json=payload, headers={"X-Request-Id": request.request_id})
        result = _Response.model_validate(data)
        if result.request_id != request.request_id:
            raise ValueError("Platform API response request_id mismatch")
        execution = result.execution
        if execution.provider == "unknown":
            raise ValueError("Platform API response missing execution provenance")
        return LLMResponse(request_id=result.request_id, content=result.content,
            finish_reason=result.finish_reason, usage=LLMUsage(**result.usage.model_dump()),
            execution=LLMExecution(provider=execution.provider, model=execution.model, node=execution.node,
                queue_wait_ms=execution.queue_wait_ms, duration_ns=round(execution.duration_ms * 1_000_000)))

    def stream(self, request: LLMRequest):
        raise NotImplementedError("Platform API v1 does not support streaming")

    def health(self) -> ProviderHealth:
        try:
            data = self._call("GET", "/api/v1/health", timeout=self.health_timeout)
            if data.get("schema_version") != 1 or type(data.get("readiness")) is not bool:
                raise ValueError("malformed Platform API health response")
            return ProviderHealth("ready" if data["readiness"] else "degraded")
        except (httpx.HTTPError, ValueError, AttributeError):
            return ProviderHealth("unavailable", "Platform API health check failed")

    def describe(self) -> ProviderDescriptor:
        return ProviderDescriptor(provider_id="platform-api-v1", provider_type="llm", node_id=None,
            capabilities=self.capabilities, models=("reasoning-main",), status=self.health().status)
