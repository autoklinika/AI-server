from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import event, select

from ai_bridge.knowledge.content_store import FileContentStore
from ai_bridge.knowledge.jsonl_ingestion import (
    JSONL_CHUNK_PROFILE,
    JsonlIngestRequest,
    JsonlKnowledgeIngestor,
)
from ai_bridge.knowledge.storage.models import KnowledgeChunkModel
from ai_bridge.knowledge.storage.repository import KnowledgeRepository
from ai_bridge.storage.base import Base
from ai_bridge.storage.database import Database


INDEX_PROFILE = "dense-bge-m3-1024-cosine-v1"


def setup_ingestor(tmp_path: Path):
    database = Database("sqlite:///" + str(tmp_path / "knowledge.sqlite"))

    @event.listens_for(database.engine, "connect")
    def enable_fk(dbapi_connection, _record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(database.engine)
    repository = KnowledgeRepository(database)
    ingestor = JsonlKnowledgeIngestor(
        repository=repository,
        content_store=FileContentStore(tmp_path / "objects"),
    )
    return database, repository, ingestor


def request(path: Path, revision: str = "ers-commit-a") -> JsonlIngestRequest:
    return JsonlIngestRequest(
        path=path,
        source_uri="github://autoklinika/EcuRepairService",
        document_uri="github://autoklinika/EcuRepairService/source/facts.jsonl",
        source_revision=revision,
        domain="ecu-repair",
        namespace="ecu-repair",
        index_profile=INDEX_PROFILE,
        source_title="EcuRepairService",
        source_metadata={"repository": "autoklinika/EcuRepairService"},
        document_metadata={"repository_path": "source/facts.jsonl"},
    )


def write_records(path: Path) -> None:
    rows = [
        {"id": "ERS-DK-0003", "source_id": "ASCv0-NXP-001",
         "topic": "output_driver", "fact": "Open load example."},
        {"id": "ERS-DK-0017", "source_id": "ASCv0-NXP-007",
         "topic": "CAN", "fact": "Communication may remain possible."},
    ]
    path.write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n",
        encoding="utf-8",
    )


def test_jsonl_ingestion_is_idempotent_and_record_addressable(tmp_path: Path):
    database, repository, ingestor = setup_ingestor(tmp_path)
    path = tmp_path / "facts.jsonl"
    write_records(path)

    first = ingestor.ingest(request(path))
    second = ingestor.ingest(request(path))

    assert first.record_count == 2
    assert first.canonical.version_created is True
    assert first.canonical.chunks_created == 2
    assert second.canonical.version_created is False
    assert second.canonical.chunks_created == 0
    assert second.canonical.index_job_id == first.canonical.index_job_id

    work = repository.get_index_work(first.canonical.index_job_id)
    assert [chunk.locator["record_id"] for chunk in work.chunks] == [
        "ERS-DK-0003", "ERS-DK-0017"
    ]
    assert all(chunk.chunk_profile == JSONL_CHUNK_PROFILE for chunk in work.chunks)
    assert "ERS-DK-0003" in work.chunks[0].text
    assert "ASCv0-NXP-001" in work.chunks[0].text
    database.dispose()


def test_jsonl_ingestion_preserves_repository_path_metadata(tmp_path: Path):
    database, _repository, ingestor = setup_ingestor(tmp_path)
    path = tmp_path / "facts.jsonl"
    write_records(path)
    outcome = ingestor.ingest(request(path))

    with database.session() as session:
        chunk = session.scalar(select(KnowledgeChunkModel).order_by(
            KnowledgeChunkModel.ordinal
        ))
        assert chunk.locator["record_id"] == "ERS-DK-0003"
        assert chunk.locator["line"] == 1
        assert chunk.metadata_json["record_id"] == "ERS-DK-0003"
    assert outcome.content_sha256
    database.dispose()


@pytest.mark.parametrize("lines, match", [
    (['{"id":"dup"}', '{"id":"dup"}'], "duplicate id"),
    (['{"source_id":"missing-id"}'], "non-empty string id required"),
    (["not-json"], "invalid JSON"),
])
def test_jsonl_ingestion_fails_closed_on_bad_records(
    tmp_path: Path, lines: list[str], match: str
):
    database, _repository, ingestor = setup_ingestor(tmp_path)
    path = tmp_path / "facts.jsonl"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match=match):
        ingestor.ingest(request(path))
    database.dispose()
