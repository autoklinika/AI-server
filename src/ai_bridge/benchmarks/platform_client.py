"""Stable Platform API client used by benchmark runners."""
from __future__ import annotations

from typing import Any, Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field


class _Public(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True, allow_inf_nan=False)


class SearchSource(_Public):
    type: str
    uri: str
    title: str | None = None


class SearchHit(_Public):
    result_id: str
    text: str
    score: float
    source: SearchSource
    metadata: dict[str, Any] = Field(default_factory=dict)


class SearchResponse(_Public):
    schema_version: Literal[1]
    request_id: str
    mode: str
    backend: str
    duration_ms: float | None = None
    results: list[SearchHit]


class HealthResponse(_Public):
    schema_version: Literal[1]
    readiness: bool
    status: str
    components: dict[str, Any] = Field(default_factory=dict)


class AIExecution(_Public):
    provider: str
    model: str
    node: str
    queue_wait_ms: float = Field(ge=0)
    duration_ms: float = Field(ge=0)


class AIResponse(_Public):
    schema_version: Literal[1]
    request_id: str
    state: Literal["completed"]
    content: str
    finish_reason: str
    usage: dict[str, int | None]
    execution: AIExecution


class AskResponse(_Public):
    schema_version: Literal[1]
    request_id: str
    answer: str
    claims: list[dict[str, Any]]
    insufficient_context: bool
    insufficiency_reason: str | None = None
    citations: list[dict[str, Any]]
    retrieval: dict[str, Any]
    execution: dict[str, Any] | None = None
    usage: dict[str, int | None] = Field(default_factory=dict)


class PlatformBenchmarkClient:
    """HTTP-only client: never talks to Ollama, Qdrant or provider internals."""

    def __init__(
        self,
        base_url: str,
        *,
        token: str | None = None,
        transport=None,
        timeout_seconds: float = 600.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.headers = {"Authorization": f"Bearer {token}"} if token else {}
        self.transport = transport
        self.timeout = httpx.Timeout(timeout_seconds, connect=min(10.0, timeout_seconds))

    def _call(self, method: str, path: str, **kwargs) -> dict:
        with httpx.Client(
            headers=self.headers,
            timeout=self.timeout,
            transport=self.transport,
            trust_env=False,
        ) as client:
            response = client.request(method, self.base_url + path, **kwargs)
            response.raise_for_status()
            return response.json()

    @staticmethod
    def _context(request_id: str, domain: str) -> dict:
        return {"request_id": request_id, "domain": domain}

    def health(self) -> HealthResponse:
        data = self._call("GET", "/api/v1/health")
        return HealthResponse.model_validate(data)

    def assert_ready(self) -> HealthResponse:
        health = self.health()
        if not health.readiness:
            raise RuntimeError("AI Platform is not benchmark-ready")
        manager = health.components.get("resource_manager") or {}
        if manager.get("status") != "ready":
            raise RuntimeError("Resource Manager is not ready")
        return health

    def operations(self) -> dict[str, Any]:
        return self._call("GET", "/api/v1/operations")

    def ai_structured(
        self,
        *,
        request_id: str,
        message: str,
        response_schema: dict,
        model: str = "reasoning-main",
        model_num_ctx: int = 65536,
        model_num_gpu: int = 99,
        domain: str = "ecu-repair",
        priority_class: str = "background",
    ) -> AIResponse:
        path = "/api/v1/ai" if model == "reasoning-main" else "/api/v1/benchmarks/ai"
        payload = {
            "schema_version": 1,
            "capability": "structured-generation",
            "model": model,
            "context": self._context(request_id, domain),
            "priority_class": priority_class,
            "messages": [{"role": "user", "content": message}],
            "response_schema": response_schema,
            "temperature": 0,
            "timeout_seconds": 300,
        }
        if model != "reasoning-main":
            payload["num_ctx"] = model_num_ctx
            payload["num_gpu"] = model_num_gpu
        data = self._call(
            "POST", path, json=payload, headers={"X-Request-Id": request_id}
        )
        return AIResponse.model_validate(data)

    def knowledge_search(
        self,
        *,
        request_id: str,
        query: str,
        mode: str = "hybrid",
        limit: int = 10,
        rerank: bool = True,
        domain: str = "ecu-repair",
    ) -> SearchResponse:
        data = self._call("POST", "/api/v1/knowledge/search", json={
            "schema_version": 1,
            "context": self._context(request_id, domain),

            "query": query,
            "mode": mode,
            "limit": limit,
            "rerank": rerank,
        }, headers={"X-Request-Id": request_id})
        return SearchResponse.model_validate(data)

    def knowledge_ask(
        self,
        *,
        request_id: str,
        query: str,
        mode: str = "hybrid",
        limit: int = 8,
        domain: str = "ecu-repair",
        priority_class: str = "background",
    ) -> AskResponse:
        data = self._call("POST", "/api/v1/knowledge/ask", json={
            "schema_version": 1,
            "context": self._context(request_id, domain),
            "query": query,
            "mode": mode,
            "limit": limit,
            "priority_class": priority_class,
            "timeout_seconds": 300,
            "require_grounding_signal": True,
        }, headers={"X-Request-Id": request_id})
        return AskResponse.model_validate(data)
