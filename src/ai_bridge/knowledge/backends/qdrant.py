from __future__ import annotations

import re
from time import monotonic
from typing import Any

import httpx

from ai_bridge.providers.contracts import (
    KnowledgeQuery,
    KnowledgeResult,
    KnowledgeSearchResult,
    KnowledgeSource,
    ProviderDescriptor,
    ProviderHealth,
)


_FILTER_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_RESERVED_PAYLOAD = {"text", "source_type", "source_uri", "source_title"}


class QdrantKnowledgeBackend:
    """Qdrant adapter behind the stable KnowledgeBackend contract."""
    def __init__(
        self,
        *,
        url: str,
        collection: str,
        vector_name: str = "dense",
        api_key: str | None = None,
        timeout_seconds: float = 5.0,
        logical_backend_id: str = "knowledge-primary",
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        headers = {"api-key": api_key} if api_key else {}
        self.collection = collection
        self.vector_name = vector_name
        self.logical_backend_id = logical_backend_id
        self._client = httpx.Client(
            base_url=url.rstrip("/"), headers=headers, timeout=timeout_seconds,
            transport=transport, trust_env=False,
        )

    def close(self) -> None:
        self._client.close()
    def health(self) -> ProviderHealth:
        try:
            response = self._client.get("/readyz")
            response.raise_for_status()
            return ProviderHealth(status="ready")
        except Exception as exc:
            return ProviderHealth(status="unavailable", detail=type(exc).__name__)

    def describe(self) -> ProviderDescriptor:
        health = self.health()
        return ProviderDescriptor(
            provider_id=self.logical_backend_id,
            provider_type="knowledge-backend",
            node_id=None,
            capabilities=("semantic-search", "metadata-filtering", "source-attribution"),
            models=(),
            status=health.status,
            metadata={"contract_version": 1},
        )

    def search(self, query: KnowledgeQuery) -> KnowledgeSearchResult:
        if query.mode not in {"semantic", "auto"}:
            raise ValueError("backend capability unavailable for requested mode")
        if query.query_embedding is None:
            raise ValueError("semantic query requires query_embedding")
        request_body = {
            "query": list(query.query_embedding),
            "using": self.vector_name,
            "filter": self._build_filter(query),
            "limit": query.limit,
            "with_payload": True,
            "with_vector": False,
        }
        started = monotonic()
        response = self._client.post(
            f"/collections/{self.collection}/points/query", json=request_body,
        )
        response.raise_for_status()
        payload = response.json()
        points = (payload.get("result") or {}).get("points") or []
        results = tuple(self._map_point(point) for point in points)
        return KnowledgeSearchResult(
            request_id=query.request_id,
            results=results,
            backend=self.logical_backend_id,
            duration_ms=(monotonic() - started) * 1000.0,
            backend_metadata={"contract_version": 1},
        )
    @staticmethod
    def _condition(key: str, value: Any) -> dict[str, Any]:
        if not _FILTER_KEY.fullmatch(key):
            raise ValueError("invalid filter key")
        if isinstance(value, (list, tuple)):
            if not value or not all(isinstance(item, (str, int, bool)) for item in value):
                raise ValueError("filter lists must contain scalar values")
            return {"key": key, "match": {"any": list(value)}}
        if not isinstance(value, (str, int, bool)):
            raise ValueError("filters support string, integer and boolean equality")
        return {"key": key, "match": {"value": value}}

    def _build_filter(self, query: KnowledgeQuery) -> dict[str, Any]:
        must = [self._condition("domain", query.domain)]
        if query.namespaces:
            must.append(self._condition("namespace", query.namespaces))
        if query.source_types:
            must.append(self._condition("source_type", query.source_types))
        for key, value in query.filters.items():
            must.append(self._condition(key, value))
        return {"must": must}
    @staticmethod
    def _map_point(point: dict[str, Any]) -> KnowledgeResult:
        payload = point.get("payload") or {}
        text = payload.get("text")
        source_type = payload.get("source_type")
        source_uri = payload.get("source_uri")
        if not isinstance(text, str) or not text.strip():
            raise ValueError("indexed point has no text")
        if not isinstance(source_type, str) or not source_type:
            raise ValueError("indexed point has no source_type")
        if not isinstance(source_uri, str) or not source_uri:
            raise ValueError("indexed point has no source_uri")
        title = payload.get("source_title")
        metadata = {key: value for key, value in payload.items() if key not in _RESERVED_PAYLOAD}
        return KnowledgeResult(
            result_id=str(point["id"]),
            text=text,
            source=KnowledgeSource(
                type=source_type, uri=source_uri,
                title=title if isinstance(title, str) else None,
            ),
            score=float(point.get("score", 0.0)),
            metadata=metadata,
        )
