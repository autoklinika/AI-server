from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import replace

from ai_bridge.knowledge.backends import (
    CanonicalLexicalKnowledgeBackend,
    CompositeKnowledgeBackend,
    QdrantKnowledgeBackend,
)
from ai_bridge.knowledge.rerank import TechnicalEvidenceReranker
from ai_bridge.knowledge.service import KnowledgeService
from ai_bridge.knowledge.storage.repository import (
    KnowledgeDocumentSnapshot,
    KnowledgeRepository,
)
from ai_bridge.providers.contracts import KnowledgeQuery, KnowledgeSearchResult
from ai_bridge.providers.ollama import OllamaEmbeddingAdapter
from ai_bridge.settings import Settings
from ai_bridge.storage.database import Database


class KnowledgeRuntime(AbstractContextManager["KnowledgeRuntime"]):
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.database = Database(settings.database_url)
        self.repository = KnowledgeRepository(self.database)
        self.embedding = OllamaEmbeddingAdapter.from_endpoint(
            base_url=settings.gateway_url,
            default_model=settings.knowledge_embedding_model,
            timeout_seconds=300,
            request_source="knowledge-runtime",
            request_priority=settings.gateway_priority_interactive,
            provider_id="embedding-local",
            node_id=settings.node_id,
            keep_alive="2m",
        )
        self.dense = QdrantKnowledgeBackend(
            url=settings.knowledge_qdrant_url,
            collection=settings.knowledge_qdrant_collection,
        )
        self.lexical = CanonicalLexicalKnowledgeBackend(self.repository)
        self.backend = CompositeKnowledgeBackend(
            dense=self.dense,
            lexical=self.lexical,
        )
        self.service = KnowledgeService(self.backend, self.embedding)
        self.reranker = TechnicalEvidenceReranker()

    def search(self, query: KnowledgeQuery) -> KnowledgeSearchResult:
        requested_limit = query.limit
        candidate_limit = min(100, max(requested_limit * 4, 20))
        candidate_query = replace(query, limit=candidate_limit)
        result = self.service.search(candidate_query)
        reranked = self.reranker.rerank(
            query,
            result.results,
            limit=requested_limit,
        )
        return replace(
            result,
            results=reranked,
            backend_metadata={
                **result.backend_metadata,
                "reranker": "technical-evidence-v1",
            },
        )

    def get_document(self, document_id: str) -> KnowledgeDocumentSnapshot:
        return self.repository.get_current_document(document_id)

    def close(self) -> None:
        self.dense.close()
        self.database.dispose()

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()
