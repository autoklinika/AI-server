from __future__ import annotations

from dataclasses import dataclass

import httpx


@dataclass(frozen=True)
class OllamaClient:
    base_url: str
    timeout_seconds: float = 2.0

    def is_available(self) -> bool:
        try:
            response = httpx.get(
                f"{self.base_url.rstrip('/')}/api/tags",
                timeout=self.timeout_seconds,
            )
            return response.is_success
        except httpx.HTTPError:
            return False
