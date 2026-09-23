from __future__ import annotations

from pathlib import Path

from ai_bridge.knowledge.backends import (
    CanonicalLexicalKnowledgeBackend,
    CompositeKnowledgeBackend,
)
from ai_bridge.knowledge.chunking import MarkdownChunker
from ai_bridge.knowledge.content_store import FileContentStore
from ai_bridge.knowledge.ingestion import MarkdownIngestRequest, MarkdownKnowledgeIngestor
from ai_bridge.knowledge.storage.repository import KnowledgeRepository
from ai_bridge.providers.contracts import (
    KnowledgeQuery,
    KnowledgeResult,
    KnowledgeSearchResult,
    KnowledgeSource,
    ProviderDescriptor,
    ProviderHealth,
)
from ai_bridge.storage.base import Base
from ai_bridge.storage.database import Database


def ingest(tmp_path: Path):
    database = Database("sqlite:///" + str(tmp_path / "knowledge.sqlite"))
    Base.metadata.create_all(database.engine)
    repository = KnowledgeRepository(database)
    ingestor = MarkdownKnowledgeIngestor(
        repository=repository,
        chunker=MarkdownChunker(max_chars=512, profile="md-heading-512-test"),
        content_store=FileContentStore(tmp_path / "objects"),
    )
    docs = {
        "sensor.md": (
            "# Bosch sensor\n\n"
            "SPN 107 FMI 3 uses Bosch sensor 0 281 007 439. "
            "AFDPS signal enters ECU pin K82."
        ),
        "wvc.md": (
            "# WVC replay\n\n"
            "The --end-at option is historical replay only and does not prove "
            "current device connectivity."
        ),
        "noise.md": (
            "# General diagnostics\n\n"
            "CAN diagnostics and sensor wiring without the requested part number."
        ),
    }
    for name, text in docs.items():
        path = tmp_path / name
        path.write_text(text, encoding="utf-8")
        ingestor.ingest(MarkdownIngestRequest(
            path=path,
            source_uri="repo://test",
            document_uri=f"repo://test/{name}",
            source_revision="rev-1",
            domain="wvc" if name == "wvc.md" else "ecu-repair",
            namespace="wvc" if name == "wvc.md" else "ecu-repair",
            index_profile="dense-test-v1",
            source_type="documentation",
            document_metadata={"name": name},
        ))
    return database, repository


def query(text: str, *, domain="ecu-repair", mode="keyword", limit=5):
    return KnowledgeQuery(
        request_id="req-1",
        domain=domain,
        query=text,
        mode=mode,
        namespaces=(domain,),
        source_types=("documentation",),
        limit=limit,
        query_embedding=(0.1, 0.2, 0.3) if mode in {"semantic", "hybrid", "auto"} else None,
    )


def test_exact_identifier_and_keyword_search_use_current_canonical_chunks(tmp_path: Path):
    database, repository = ingest(tmp_path)
    backend = CanonicalLexicalKnowledgeBackend(repository)

    exact = backend.search(query("0 281 007 439", mode="exact"))
    assert exact.results
    assert "0 281 007 439" in exact.results[0].text
    assert exact.results[0].metadata["chunk_id"].startswith("kchk_")

    replay = backend.search(query("--end-at historical", domain="wvc", mode="keyword"))
    assert replay.results
    assert "--end-at" in replay.results[0].text
    assert "historical" in replay.results[0].text.casefold()

    filtered = KnowledgeQuery(
        request_id="req-filter",
        domain="ecu-repair",
        query="K82",
        mode="keyword",
        namespaces=("ecu-repair",),
        source_types=("documentation",),
        filters={"name": "sensor.md"},
        limit=5,
    )
    hits = backend.search(filtered).results
    assert hits and all(hit.metadata["name"] == "sensor.md" for hit in hits)
    database.dispose()


class FakeDenseBackend:
    def __init__(self, wrong: KnowledgeResult, correct: KnowledgeResult):
        self.wrong = wrong
        self.correct = correct

    def search(self, request):
        return KnowledgeSearchResult(
            request_id=request.request_id,
            backend="dense-private",
            results=(self.wrong, self.correct),
        )

    def health(self):
        return ProviderHealth(status="ready")

    def describe(self):
        return ProviderDescriptor(
            provider_id="dense-private",
            provider_type="knowledge-backend",
            node_id=None,
            capabilities=("semantic",),
            models=(),
            status="ready",
        )


def test_hybrid_rrf_promotes_lexical_exact_evidence_without_exposing_backend(tmp_path: Path):
    database, repository = ingest(tmp_path)
    lexical = CanonicalLexicalKnowledgeBackend(repository)
    lexical_hits = lexical.search(query("0 281 007 439", mode="keyword")).results
    correct = lexical_hits[0]
    wrong = KnowledgeResult(
        result_id="dense-wrong",
        text="Generic CAN diagnostic information.",
        source=KnowledgeSource(
            type="documentation",
            uri="repo://test/noise.md",
            title="Noise",
        ),
        score=0.99,
        metadata={"chunk_id": "wrong-chunk"},
    )
    dense_correct = KnowledgeResult(
        result_id="dense-correct",
        text=correct.text,
        source=correct.source,
        score=0.80,
        metadata=dict(correct.metadata),
    )
    backend = CompositeKnowledgeBackend(
        dense=FakeDenseBackend(wrong, dense_correct),
        lexical=lexical,
    )

    result = backend.search(query("0 281 007 439", mode="hybrid", limit=3))
    assert result.backend == "knowledge-primary"
    assert result.results[0].metadata["chunk_id"] == correct.metadata["chunk_id"]
    assert result.results[0].metadata["fusion"]["dense_rank"] == 2
    assert result.results[0].metadata["fusion"]["lexical_rank"] == 1
    assert "dense-private" not in repr(result)

    exact = backend.search(query("0 281 007 439", mode="exact"))
    assert exact.backend == "knowledge-primary"
    assert "0 281 007 439" in exact.results[0].text
    database.dispose()
