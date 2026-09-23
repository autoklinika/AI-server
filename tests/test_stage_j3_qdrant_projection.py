from __future__ import annotations

import json
from pathlib import Path

import httpx

from ai_bridge.knowledge.chunking import MarkdownChunker
from ai_bridge.knowledge.content_store import FileContentStore
from ai_bridge.knowledge.indexing import DenseIndexProfile, QdrantKnowledgeProjector
from ai_bridge.knowledge.ingestion import MarkdownIngestRequest, MarkdownKnowledgeIngestor
from ai_bridge.knowledge.storage.models import KnowledgeIndexJobModel
from ai_bridge.knowledge.storage.repository import KnowledgeRepository
from ai_bridge.providers.contracts import EmbeddingResult, EmbeddingVector
from ai_bridge.storage.base import Base
from ai_bridge.storage.database import Database


class FakeEmbeddingProvider:
    def __init__(self):
        self.calls = []

    def embed(self, request):
        self.calls.append(request)
        vectors = tuple(
            EmbeddingVector(index=i, values=(1.0, float(i), 0.5))
            for i, _ in enumerate(request.inputs)
        )
        return EmbeddingResult(
            request_id=request.request_id,
            vectors=vectors,
            provider="embedding-test",
            model="test",
            dimensions=3,
        )


    def health(self):
        raise NotImplementedError

    def describe(self):
        raise NotImplementedError


def prepare(tmp_path: Path):
    database = Database("sqlite:///" + str(tmp_path / "knowledge.sqlite"))
    Base.metadata.create_all(database.engine)
    repository = KnowledgeRepository(database)
    path = tmp_path / "doc.md"
    path.write_text(
        "# Hatz C81\n\nSPN 107 FMI 3.\n\nK82 is the AFDPS signal.",
        encoding="utf-8",
    )
    outcome = MarkdownKnowledgeIngestor(
        repository=repository,
        chunker=MarkdownChunker(max_chars=256, profile="md-heading-256-test"),
        content_store=FileContentStore(tmp_path / "objects"),
    ).ingest(MarkdownIngestRequest(
        path=path,
        source_uri="github://autoklinika/EcuRepairService",
        document_uri="github://autoklinika/EcuRepairService/test/doc.md",
        source_revision="commit-a",
        domain="ecu-repair",
        namespace="ecu-repair",
        index_profile="dense-test-v1",
        source_title="EcuRepairService",
    ))
    return database, repository, outcome


def test_projection_is_idempotent_and_carries_canonical_provenance(tmp_path: Path):
    database, repository, outcome = prepare(tmp_path)
    seen = {"created": False, "deleted": [], "upserts": []}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if request.method == "GET" and path == "/collections/knowledge_test":
            if not seen["created"]:
                return httpx.Response(404, request=request)
            return httpx.Response(200, json={
                "result": {
                    "config": {
                        "params": {
                            "vectors": {
                                "dense": {"size": 3, "distance": "Cosine"}
                            }
                        }
                    }
                }
            }, request=request)
        if request.method == "PUT" and path == "/collections/knowledge_test":
            seen["created"] = True
            return httpx.Response(200, json={"status": "ok"}, request=request)
        if request.method == "PUT" and path.endswith("/index"):
            return httpx.Response(200, json={"status": "ok"}, request=request)
        if request.method == "POST" and path.endswith("/points/delete"):
            seen["deleted"].append(json.loads(request.content))
            return httpx.Response(200, json={"status": "ok"}, request=request)
        if request.method == "PUT" and path.endswith("/points"):
            seen["upserts"].append(json.loads(request.content))
            return httpx.Response(200, json={"status": "ok"}, request=request)
        raise AssertionError(f"unexpected request: {request.method} {path}")

    embedding = FakeEmbeddingProvider()
    projector = QdrantKnowledgeProjector(
        repository=repository,
        embedding_provider=embedding,
        qdrant_url="http://qdrant.invalid",
        profile=DenseIndexProfile(
            profile_id="dense-test-v1",
            collection="knowledge_test",
            dimensions=3,
            batch_size=8,
        ),
        transport=httpx.MockTransport(handler),
    )
    try:
        assert projector.project(outcome.canonical.index_job_id) is True
        assert projector.project(outcome.canonical.index_job_id) is False
    finally:
        projector.close()

    assert len(embedding.calls) == 1
    assert embedding.calls[0].context["embedding_role"] == "document"
    assert len(seen["deleted"]) == 1
    assert len(seen["upserts"]) == 1

    points = seen["upserts"][0]["points"]
    assert points
    payload = points[0]["payload"]
    assert payload["domain"] == "ecu-repair"
    assert payload["namespace"] == "ecu-repair"
    assert payload["source_id"].startswith("ksrc_")
    assert payload["document_id"].startswith("kdoc_")
    assert payload["version_id"].startswith("kver_")
    assert payload["chunk_id"].startswith("kchk_")
    assert payload["chunk_profile"] == "md-heading-256-test"
    assert payload["source_revision"] == "commit-a"

    with database.session() as session:
        job = session.get(KnowledgeIndexJobModel, outcome.canonical.index_job_id)
        assert job.state == "completed"
        assert job.attempts == 1
        assert job.completed_at is not None
    database.dispose()


def test_projection_failure_is_retryable(tmp_path: Path):
    database, repository, outcome = prepare(tmp_path)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(404, request=request)
        if request.method == "PUT" and request.url.path == "/collections/knowledge_test":
            return httpx.Response(200, json={"status": "ok"}, request=request)
        if request.method == "PUT" and request.url.path.endswith("/index"):
            return httpx.Response(200, json={"status": "ok"}, request=request)
        return httpx.Response(503, text="temporary", request=request)

    projector = QdrantKnowledgeProjector(
        repository=repository,
        embedding_provider=FakeEmbeddingProvider(),
        qdrant_url="http://qdrant.invalid",
        profile=DenseIndexProfile(
            profile_id="dense-test-v1",
            collection="knowledge_test",
            dimensions=3,
        ),
        transport=httpx.MockTransport(handler),
    )
    try:
        try:
            projector.project(outcome.canonical.index_job_id)
        except httpx.HTTPStatusError:
            pass
        else:
            raise AssertionError("projection failure must surface")
    finally:
        projector.close()

    with database.session() as session:
        job = session.get(KnowledgeIndexJobModel, outcome.canonical.index_job_id)
        assert job.state == "failed"
        assert job.attempts == 1
        assert "HTTPStatusError" in job.last_error
    assert repository.pending_job_ids() == (outcome.canonical.index_job_id,)
    database.dispose()
