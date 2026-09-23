from __future__ import annotations

import argparse
import json

from ai_bridge.knowledge.indexing import DenseIndexProfile, QdrantKnowledgeProjector
from ai_bridge.knowledge.storage.repository import KnowledgeRepository
from ai_bridge.providers.ollama import OllamaEmbeddingAdapter
from ai_bridge.settings import Settings
from ai_bridge.storage.database import Database


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--job-id", action="append", default=[])
    parser.add_argument("--fail-fast", action="store_true")
    args = parser.parse_args()

    settings = Settings()
    database = Database(settings.database_url)
    repository = KnowledgeRepository(database)
    embedding = OllamaEmbeddingAdapter.from_endpoint(
        base_url=settings.gateway_url,
        default_model=settings.knowledge_embedding_model,
        timeout_seconds=300,
        request_source="knowledge-indexer",
        request_priority=settings.gateway_priority_background,
        provider_id="embedding-local",
        node_id=settings.node_id,
        keep_alive="2m",
    )
    projector = QdrantKnowledgeProjector(
        repository=repository,
        embedding_provider=embedding,
        qdrant_url=settings.knowledge_qdrant_url,
        profile=DenseIndexProfile(
            profile_id=settings.knowledge_index_profile,
            collection=settings.knowledge_qdrant_collection,
            dimensions=settings.knowledge_embedding_dimensions,
            vector_name="dense",
            distance="Cosine",
            batch_size=32,
        ),
        timeout_seconds=60,
    )

    if args.job_id:
        job_ids = tuple(args.job_id)
    else:
        job_ids = repository.pending_job_ids(
            limit=args.limit,
            index_profile=settings.knowledge_index_profile,
        )

    completed = 0
    skipped = 0
    failed = 0
    try:
        for job_id in job_ids:
            try:
                projected = projector.project(job_id)
                if projected:
                    completed += 1
                    state = "completed"
                else:
                    skipped += 1
                    state = "skipped"
                print(json.dumps({"job_id": job_id, "state": state}))
            except Exception as exc:
                failed += 1
                print(json.dumps({
                    "job_id": job_id,
                    "state": "failed",
                    "error": f"{type(exc).__name__}: {exc}",
                }))
                if args.fail_fast:
                    raise
    finally:
        projector.close()
        database.dispose()

    print(json.dumps({
        "summary": {
            "selected": len(job_ids),
            "completed": completed,
            "skipped": skipped,
            "failed": failed,
            "index_profile": settings.knowledge_index_profile,
            "collection": settings.knowledge_qdrant_collection,
        }
    }, indent=2))
    if failed:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
