from __future__ import annotations

from pathlib import Path

from sqlalchemy import event, func, select

from ai_bridge.knowledge.chunking import MarkdownChunker
from ai_bridge.knowledge.content_store import FileContentStore
from ai_bridge.knowledge.ingestion import MarkdownIngestRequest, MarkdownKnowledgeIngestor
from ai_bridge.knowledge.storage.models import (
    KnowledgeChunkModel,
    KnowledgeDocumentModel,
    KnowledgeDocumentVersionModel,
    KnowledgeIndexJobModel,
    KnowledgeSourceModel,
)
from ai_bridge.knowledge.storage.repository import KnowledgeRepository
from ai_bridge.storage.base import Base
from ai_bridge.storage.database import Database


INDEX_PROFILE = "dense-bge-m3-1024-cosine-v1"


def setup_repo(tmp_path: Path):
    database = Database("sqlite:///" + str(tmp_path / "knowledge.sqlite"))

    @event.listens_for(database.engine, "connect")
    def enable_foreign_keys(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(database.engine)
    repository = KnowledgeRepository(database)
    ingestor = MarkdownKnowledgeIngestor(
        repository=repository,
        chunker=MarkdownChunker(max_chars=2400, profile="md-heading-2400-v1"),
        content_store=FileContentStore(tmp_path / "objects"),
    )
    return database, repository, ingestor


def request(path: Path, revision: str = "commit-a") -> MarkdownIngestRequest:
    return MarkdownIngestRequest(
        path=path,
        source_uri="github://autoklinika/EcuRepairService",
        document_uri="github://autoklinika/EcuRepairService/cases/case-1.md",
        source_revision=revision,
        domain="ecu-repair",
        namespace="ecu-repair",
        index_profile=INDEX_PROFILE,
        source_title="EcuRepairService",
        source_metadata={"repository": "autoklinika/EcuRepairService"},
        document_metadata={"path": "cases/case-1.md"},
    )


def counts(database: Database) -> tuple[int, int, int, int, int]:
    with database.session() as session:
        return (
            session.scalar(select(func.count()).select_from(KnowledgeSourceModel)),
            session.scalar(select(func.count()).select_from(KnowledgeDocumentModel)),
            session.scalar(select(func.count()).select_from(KnowledgeDocumentVersionModel)),
            session.scalar(select(func.count()).select_from(KnowledgeChunkModel)),
            session.scalar(select(func.count()).select_from(KnowledgeIndexJobModel)),
        )


def test_same_content_is_idempotent(tmp_path: Path):
    database, repository, ingestor = setup_repo(tmp_path)
    path = tmp_path / "case.md"
    path.write_text("# Case\n\nSPN 107 FMI 3 caused by damaged wire.", encoding="utf-8")

    first = ingestor.ingest(request(path))
    second = ingestor.ingest(request(path))

    assert first.canonical.source_created is True
    assert first.canonical.document_created is True
    assert first.canonical.version_created is True
    assert first.canonical.current_changed is True
    assert first.canonical.chunks_created > 0
    assert second.canonical.source_created is False
    assert second.canonical.document_created is False
    assert second.canonical.version_created is False
    assert second.canonical.current_changed is False
    assert second.canonical.chunks_created == 0
    assert second.canonical.index_job_id == first.canonical.index_job_id
    assert counts(database) == (1, 1, 1, first.chunk_count, 1)
    assert repository.pending_job_ids() == (first.canonical.index_job_id,)
    database.dispose()


def test_changed_content_creates_version_and_supersedes_stale_pending_job(tmp_path: Path):
    database, repository, ingestor = setup_repo(tmp_path)
    path = tmp_path / "case.md"
    path.write_text("# Case\n\nFirst diagnosis.", encoding="utf-8")
    first = ingestor.ingest(request(path, "commit-a"))

    path.write_text("# Case\n\nCorrected diagnosis with K82 signal.", encoding="utf-8")
    second = ingestor.ingest(request(path, "commit-b"))

    assert second.content_sha256 != first.content_sha256
    assert second.canonical.version_created is True
    assert second.canonical.current_changed is True
    assert second.canonical.index_job_id != first.canonical.index_job_id

    with database.session() as session:
        first_job = session.get(KnowledgeIndexJobModel, first.canonical.index_job_id)
        second_job = session.get(KnowledgeIndexJobModel, second.canonical.index_job_id)
        document = session.scalar(select(KnowledgeDocumentModel))
        assert first_job.state == "superseded"
        assert second_job.state == "pending"
        assert document.current_version_id == second_job.version_id

    assert repository.pending_job_ids() == (second.canonical.index_job_id,)
    database.dispose()


def test_reverting_to_previous_content_reuses_version_and_requeues_index(tmp_path: Path):
    database, repository, ingestor = setup_repo(tmp_path)
    path = tmp_path / "case.md"
    original = "# Case\n\nOriginal diagnosis."
    path.write_text(original, encoding="utf-8")
    first = ingestor.ingest(request(path, "commit-a"))
    assert repository.mark_index_running(first.canonical.index_job_id)
    repository.mark_index_completed(first.canonical.index_job_id)

    path.write_text("# Case\n\nTemporary correction.", encoding="utf-8")
    second = ingestor.ingest(request(path, "commit-b"))
    assert repository.mark_index_running(second.canonical.index_job_id)
    repository.mark_index_completed(second.canonical.index_job_id)

    path.write_text(original, encoding="utf-8")
    reverted = ingestor.ingest(request(path, "commit-c"))

    assert reverted.canonical.version_created is False
    assert reverted.canonical.current_changed is True
    assert reverted.canonical.index_job_id == first.canonical.index_job_id
    assert reverted.canonical.index_job_state == "pending"
    assert counts(database)[2] == 2

    work = repository.get_index_work(reverted.canonical.index_job_id)
    assert work.version.content_sha256 == reverted.content_sha256
    assert work.source.uri == "github://autoklinika/EcuRepairService"
    assert work.chunks[0].chunk_profile == "md-heading-2400-v1"
    database.dispose()


def test_chunk_profile_changes_do_not_collide(tmp_path: Path):
    database, repository, _ingestor = setup_repo(tmp_path)
    path = tmp_path / "case.md"
    path.write_text("# Case\n\nA short document about CAN1 diagnostics.", encoding="utf-8")

    first = MarkdownKnowledgeIngestor(
        repository=repository,
        chunker=MarkdownChunker(max_chars=1200, profile="md-heading-1200-v1"),
        content_store=FileContentStore(tmp_path / "objects"),
    ).ingest(request(path))

    second = MarkdownKnowledgeIngestor(
        repository=repository,
        chunker=MarkdownChunker(max_chars=2400, profile="md-heading-2400-v1"),
        content_store=FileContentStore(tmp_path / "objects"),
    ).ingest(request(path))

    assert first.content_sha256 == second.content_sha256
    assert second.canonical.version_created is False
    assert second.canonical.chunks_created > 0
    assert second.canonical.index_job_id != first.canonical.index_job_id

    with database.session() as session:
        profiles = set(session.scalars(
            select(KnowledgeChunkModel.chunk_profile)
        ).all())
    assert profiles == {"md-heading-1200-v1", "md-heading-2400-v1"}
    database.dispose()

def test_ingestion_preserves_immutable_source_bytes(tmp_path: Path):
    database, repository, ingestor = setup_repo(tmp_path)
    path = tmp_path / "case.md"
    original = "# Case\n\nOriginal immutable content."
    path.write_text(original, encoding="utf-8")

    outcome = ingestor.ingest(request(path, "commit-a"))
    work = repository.get_index_work(outcome.canonical.index_job_id)
    object_path = Path(work.version.storage_uri.removeprefix("file://"))

    assert object_path.read_text(encoding="utf-8") == original
    assert object_path.stat().st_mode & 0o222 == 0

    path.write_text("# Case\n\nSource checkout changed later.", encoding="utf-8")
    assert object_path.read_text(encoding="utf-8") == original
    assert work.version.content_sha256 == outcome.content_sha256
    database.dispose()
