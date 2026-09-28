"""Async execution port; product wire details stay behind this adapter.

Cancellation must close the HTTP operation before RM releases admission. No
threadpool work may outlive the admitted coroutine.
"""
from typing import Protocol

import httpx

from ai_bridge.providers.contracts import LLMRequest, LLMResponse, LLMUsage


class PlatformProvider(Protocol):
    provider_id: str
    node_id: str

    async def generate(self, request: LLMRequest) -> LLMResponse: ...
    async def ready(self) -> bool: ...


class GatewayLLMAdapter:
    provider_id = "ollama-local"

    def __init__(self, client: httpx.AsyncClient, model: str, node_id: str, health_timeout: float):
        self.client, self.model, self.node_id = client, model, node_id
        self.health_timeout = health_timeout

    async def _generate_model(
        self, request: LLMRequest, model: str, *, num_ctx: int | None = None, num_gpu: int | None = None
    ) -> LLMResponse:
        options = {"temperature": request.temperature}
        if num_ctx is not None:
            options["num_ctx"] = num_ctx
        if num_gpu is not None:
            options["num_gpu"] = num_gpu
        if request.max_output_tokens is not None:
            if request.max_output_tokens <= 0:
                raise ValueError("max_output_tokens must be positive")
            options["num_predict"] = request.max_output_tokens
        payload = {"model": model, "messages": request.messages,
                   "stream": False, "think": False,
                   "options": options}
        if request.response_schema is not None:
            payload["format"] = request.response_schema
        response = await self.client.post("/api/chat", json=payload)
        response.raise_for_status()
        data = response.json()
        content = data["message"]["content"]
        if data.get("done") is not True or not isinstance(content, str):
            raise ValueError("invalid provider response")
        def count(name):
            value = data.get(name)
            return value if type(value) is int and value >= 0 else None
        return LLMResponse(request_id=request.request_id, content=content,
                           usage=LLMUsage(count("prompt_eval_count"), count("eval_count")))

    async def generate(self, request: LLMRequest) -> LLMResponse:
        return await self._generate_model(request, self.model)

    async def generate_for_model(
        self, request: LLMRequest, model: str, *, num_ctx: int | None = None, num_gpu: int | None = None
    ) -> LLMResponse:
        return await self._generate_model(request, model, num_ctx=num_ctx, num_gpu=num_gpu)

    async def ready(self) -> bool:
        try:
            response = await self.client.get("/api/tags", timeout=self.health_timeout)
            response.raise_for_status()
            return any(item.get("name") == self.model or item.get("model") == self.model
                       for item in response.json()["models"])
        except Exception:
            return False
