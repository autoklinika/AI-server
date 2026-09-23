from __future__ import annotations

from dataclasses import dataclass, replace

from ai_bridge.providers.contracts import (
    EmbeddingProvider,
    EmbeddingRequest,
    KnowledgeBackend,
    KnowledgeQuery,
    KnowledgeSearchResult,
    ProviderDescriptor,
    ProviderHealth,
)


class KnowledgeContractError(RuntimeError):
    """Backend violated the stable Knowledge Service contract."""


@dataclass(frozen=True)
class KnowledgeService:
    """Stable product-neutral boundary used by platform clients."""

    backend: KnowledgeBackend
    embedding_provider: EmbeddingProvider | None = None

    def search(self, query: KnowledgeQuery) -> KnowledgeSearchResult:
        if not query.request_id or not query.domain or not query.query.strip():
            raise ValueError("request_id, domain and query are required")
        if not 1 <= query.limit <= 100:
            raise ValueError("limit must be between 1 and 100")

        backend_query = query
        if query.mode in {"semantic", "hybrid", "auto"} and query.query_embedding is None:
            if self.embedding_provider is None:
                raise ValueError("embedding provider is required for semantic retrieval")
            embedded = self.embedding_provider.embed(EmbeddingRequest(
                request_id=f"{query.request_id}:embedding",
                inputs=(query.query,),
                context={
                    "domain": query.domain,
                    "knowledge_request_id": query.request_id,
                    "embedding_role": "query",
                },
            ))
            if len(embedded.vectors) != 1 or embedded.vectors[0].index != 0:
                raise KnowledgeContractError("embedding provider returned invalid vector set")
            backend_query = replace(query, query_embedding=embedded.vectors[0].values)

        result = self.backend.search(backend_query)
        if result.request_id != query.request_id:
            raise KnowledgeContractError("backend changed request identity")

        for hit in result.results:
            if not hit.result_id or not hit.text.strip():
                raise KnowledgeContractError("backend returned an invalid result")
            if not hit.source.type or not hit.source.uri:
                raise KnowledgeContractError("source attribution is required")
        return result

    def health(self) -> ProviderHealth:
        return self.backend.health()

    def describe(self) -> ProviderDescriptor:
        return self.backend.describe()
