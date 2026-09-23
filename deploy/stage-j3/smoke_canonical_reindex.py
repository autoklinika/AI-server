from __future__ import annotations

from pathlib import Path
import tempfile
import uuid

import httpx

from ai_bridge.knowledge import KnowledgeService
from ai_bridge.knowledge.backends import (
    CanonicalLexicalKnowledgeBackend,
    CompositeKnowledgeBackend,
    QdrantKnowledgeBackend,
)
from ai_bridge.knowledge.chunking import MarkdownChunker
from ai_bridge.knowledge.content_store import FileContentStore
from ai_bridge.knowledge.indexing import DenseIndexProfile, QdrantKnowledgeProjector
from ai_bridge.knowledge.ingestion import MarkdownIngestRequest, MarkdownKnowledgeIngestor
from ai_bridge.knowledge.storage import models as _knowledge_models  # noqa: F401
from ai_bridge.knowledge.storage.repository import KnowledgeRepository
from ai_bridge.providers.contracts import KnowledgeQuery
from ai_bridge.providers.ollama import OllamaEmbeddingAdapter
from ai_bridge.settings import Settings
from ai_bridge.storage.base import Base
from ai_bridge.storage.database import Database


def main() -> None:
    settings = Settings()
    collection = "stage_j3_smoke_" + uuid.uuid4().hex[:12]
    embedding = OllamaEmbeddingAdapter.from_endpoint(
        base_url=settings.gateway_url,
        default_model=settings.knowledge_embedding_model,
        timeout_seconds=300,
        request_source="knowledge-j3-smoke",
        request_priority=settings.gateway_priority_background,
        provider_id="embedding-local",
        node_id=settings.node_id,
        keep_alive="2m",
    )
    with tempfile.TemporaryDirectory(prefix="stage-j3-") as tmp:
        root = Path(tmp)
        database = Database("sqlite:///" + str(root / "knowledge.sqlite"))
        Base.metadata.create_all(database.engine)
        repository = KnowledgeRepository(database)
        source = root / "case.md"
        source.write_text(
            "# CASE-0001\n\n"
            "SPN 107 FMI 3 on Hatz C81. "
            "Confirmed root cause: damaged electrical wire at the sensor connector.\n",
            encoding="utf-8",
        )
        outcome = MarkdownKnowledgeIngestor(
            repository=repository,
            chunker=MarkdownChunker(
                max_chars=settings.knowledge_chunk_max_chars,
                profile=settings.knowledge_chunk_profile,
            ),
            content_store=FileContentStore(root / "objects"),
        ).ingest(MarkdownIngestRequest(
            path=source,
            source_uri="smoke://stage-j3",
            document_uri="smoke://stage-j3/case.md",
            source_revision="smoke-revision-1",
            domain="ecu-repair",
            namespace="ecu-repair",
            index_profile=settings.knowledge_index_profile,
            source_type="smoke",
            source_title="Stage J3 smoke",
        ))

        projector = QdrantKnowledgeProjector(
            repository=repository,
            embedding_provider=embedding,
            qdrant_url=settings.knowledge_qdrant_url,
            profile=DenseIndexProfile(
                profile_id=settings.knowledge_index_profile,
                collection=collection,
                dimensions=settings.knowledge_embedding_dimensions,
            ),
            timeout_seconds=60,
        )
        try:
            assert projector.project(outcome.canonical.index_job_id) is True
        finally:
            projector.close()

        dense = QdrantKnowledgeBackend(
            url=settings.knowledge_qdrant_url,
            collection=collection,
        )
        lexical = CanonicalLexicalKnowledgeBackend(repository)
        composite = CompositeKnowledgeBackend(dense=dense, lexical=lexical)
        service = KnowledgeService(composite, embedding)
        try:
            result = service.search(KnowledgeQuery(
                request_id="stage-j3-smoke-query",
                domain="ecu-repair",
                query="Co było przyczyną SPN 107 FMI 3?",
                mode="semantic",
                namespaces=("ecu-repair",),
                source_types=("smoke",),
                limit=3,
            ))
            exact = service.search(KnowledgeQuery(
                request_id="stage-j3-smoke-exact",
                domain="ecu-repair",
                query="SPN 107 FMI 3",
                mode="exact",
                namespaces=("ecu-repair",),
                source_types=("smoke",),
                limit=3,
            ))
            hybrid = service.search(KnowledgeQuery(
                request_id="stage-j3-smoke-hybrid",
                domain="ecu-repair",
                query="SPN 107 FMI 3 damaged wire",
                mode="hybrid",
                namespaces=("ecu-repair",),
                source_types=("smoke",),
                limit=3,
            ))
        finally:
            dense.close()

        assert result.results
        hit = result.results[0]
        assert "damaged electrical wire" in hit.text
        assert hit.source.uri == "smoke://stage-j3/case.md"
        assert hit.metadata["document_id"].startswith("kdoc_")
        assert hit.metadata["version_id"].startswith("kver_")
        assert hit.metadata["chunk_id"].startswith("kchk_")
        assert exact.results and "SPN 107 FMI 3" in exact.results[0].text
        assert exact.backend == "knowledge-primary"
        assert hybrid.results and "damaged electrical wire" in hybrid.results[0].text
        assert hybrid.backend == "knowledge-primary"
        assert hybrid.results[0].metadata["fusion"]["method"] == "rrf-v1"

        with httpx.Client(
            base_url=settings.knowledge_qdrant_url,
            timeout=30,
            trust_env=False,
        ) as client:
            client.delete(f"/collections/{collection}").raise_for_status()

        database.dispose()
        print(
            "PASS: canonical ingest -> pending job -> scheduled BGE -> "
            "Qdrant projection -> text query -> canonical provenance"
        )


if __name__ == "__main__":
    main()
