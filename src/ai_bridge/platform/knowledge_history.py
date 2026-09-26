from __future__ import annotations

from collections import deque
from copy import deepcopy
from datetime import datetime, timezone
from threading import Lock
from uuid import uuid4


_HISTORY_LIMIT = 10


class KnowledgeAskHistory:
    """Explicit bounded user-facing history for Knowledge Ask AI responses."""

    def __init__(self, limit: int = _HISTORY_LIMIT) -> None:
        if limit < 1:
            raise ValueError("history limit must be positive")
        self.limit = limit
        self._items: deque[dict] = deque(maxlen=limit)
        self._lock = Lock()

    def add(
        self,
        *,
        query: str,
        domain: str | None,
        mode: str,
        response: dict,
    ) -> dict:
        item = {
            "history_id": "kh_" + uuid4().hex,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "query": query,
            "domain": domain,
            "mode": mode,
            "response": deepcopy(response),
        }
        with self._lock:
            self._items.append(item)
        return deepcopy(item)

    def list(self) -> list[dict]:
        with self._lock:
            items = list(reversed(self._items))
        return [
            {
                "history_id": item["history_id"],
                "created_at": item["created_at"],
                "query": item["query"],
                "domain": item["domain"],
                "mode": item["mode"],
                "insufficient_context": bool(
                    item["response"].get("insufficient_context")
                ),
                "answer_preview": str(item["response"].get("answer") or "")[:240],
                "citation_count": len(item["response"].get("citations") or []),
            }
            for item in items
        ]

    def get(self, history_id: str) -> dict:
        with self._lock:
            for item in self._items:
                if item["history_id"] == history_id:
                    return deepcopy(item)
        raise KeyError(history_id)
