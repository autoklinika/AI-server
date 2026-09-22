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

    async def generate(self, request: LLMRequest) -> LLMResponse:
        payload = {"model": self.model, "messages": request.messages,
                   "stream": False, "think": False,
                   "options": {"temperature": request.temperature}}
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

    async def ready(self) -> bool:
        try:
            response = await self.client.get("/api/tags", timeout=self.health_timeout)
            response.raise_for_status()
            return any(item.get("name") == self.model or item.get("model") == self.model
                       for item in response.json()["models"])
        except Exception:
            return False
