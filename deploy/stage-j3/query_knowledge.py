from __future__ import annotations

import argparse
import json

from ai_bridge.knowledge import KnowledgeService
from ai_bridge.knowledge.backends import (
    CanonicalLexicalKnowledgeBackend,
    CompositeKnowledgeBackend,
    QdrantKnowledgeBackend,
)
from ai_bridge.knowledge.storage.repository import KnowledgeRepository
from ai_bridge.providers.contracts import KnowledgeQuery
from ai_bridge.providers.ollama import OllamaEmbeddingAdapter
from ai_bridge.settings import Settings
from ai_bridge.storage.database import Database


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("query")
    parser.add_argument("--domain", default="ecu-repair")
    parser.add_argument(
        "--mode",
        choices=("exact", "keyword", "semantic", "hybrid", "auto"),
        default="hybrid",
    )
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--source-type", action="append", default=[])
    args = parser.parse_args()

    settings = Settings()
    database = Database(settings.database_url)
    repository = KnowledgeRepository(database)
    embedding = OllamaEmbeddingAdapter.from_endpoint(
        base_url=settings.gateway_url,
        default_model=settings.knowledge_embedding_model,
        timeout_seconds=300,
        request_source="knowledge-query-cli",
        request_priority=settings.gateway_priority_interactive,
        provider_id="embedding-local",
        node_id=settings.node_id,
        keep_alive="2m",
    )
    dense = QdrantKnowledgeBackend(
        url=settings.knowledge_qdrant_url,
        collection=settings.knowledge_qdrant_collection,
    )
    lexical = CanonicalLexicalKnowledgeBackend(repository)
    backend = CompositeKnowledgeBackend(dense=dense, lexical=lexical)
    service = KnowledgeService(backend, embedding)

    try:
        result = service.search(KnowledgeQuery(
            request_id="knowledge-cli",
            domain=args.domain,
            query=args.query,
            mode=args.mode,
            namespaces=(args.domain,),
            source_types=tuple(args.source_type),
            limit=args.limit,
        ))
        print(json.dumps({
            "request_id": result.request_id,
            "backend": result.backend,
            "duration_ms": result.duration_ms,
            "results": [
                {
                    "rank": rank,
                    "score": hit.score,
                    "text": hit.text,
                    "source": {
                        "type": hit.source.type,
                        "uri": hit.source.uri,
                        "title": hit.source.title,
                    },
                    "metadata": hit.metadata,
                }
                for rank, hit in enumerate(result.results, start=1)
            ],
        }, ensure_ascii=False, indent=2))
    finally:
        dense.close()
        database.dispose()


if __name__ == "__main__":
    main()
