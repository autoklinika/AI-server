from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx


@dataclass(frozen=True)
class OllamaChatResult:
    content: str
    model: str
    prompt_eval_count: int | None
    eval_count: int | None
    total_duration_ns: int | None


@dataclass(frozen=True)
class OllamaClient:
    base_url: str
    timeout_seconds: float = 300.0
    availability_timeout_seconds: float = 2.0

    def is_available(self) -> bool:
        try:
            response = httpx.get(
                f"{self.base_url.rstrip('/')}/api/tags",
                timeout=self.availability_timeout_seconds,
            )
            return response.is_success
        except httpx.HTTPError:
            return False

    def chat_structured(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        response_schema: dict[str, Any],
        think: bool = False,
        temperature: float = 0.0,
    ) -> OllamaChatResult:
        payload = {
            "model": model,
            "messages": messages,
            "stream": False,
            "format": response_schema,
            "think": think,
            "options": {"temperature": temperature},
        }
        try:
            response = httpx.post(
                f"{self.base_url.rstrip('/')}/api/chat",
                json=payload,
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text[:2000]
            raise RuntimeError(
                f"Ollama returned HTTP {exc.response.status_code}: {detail}"
            ) from exc
        except httpx.HTTPError as exc:
            raise RuntimeError(f"Ollama unavailable: {exc}") from exc

        data = response.json()
        message = data.get("message")
        if not isinstance(message, dict):
            raise RuntimeError("Ollama response does not contain message object")
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            raise RuntimeError("Ollama response does not contain structured content")

        def optional_int(name: str) -> int | None:
            value = data.get(name)
            return value if isinstance(value, int) else None

        return OllamaChatResult(
            content=content,
            model=str(data.get("model", model)),
            prompt_eval_count=optional_int("prompt_eval_count"),
            eval_count=optional_int("eval_count"),
            total_duration_ns=optional_int("total_duration"),
        )
