from __future__ import annotations

from hashlib import sha256
from pathlib import Path

import pytest
from sqlalchemy import event

from ai_bridge.domains.ers.artifacts import (
    ErsArtifactContentUnavailable,
    ErsArtifactService,
)
from ai_bridge.domains.ers.storage.artifact_repository import ErsArtifactRepository
from ai_bridge.domains.ers.storage.models import ErsCaseCounterModel
from ai_bridge.domains.ers.storage.repository import ErsCaseRepository
from ai_bridge.knowledge.content_store import FileContentStore
from ai_bridge.storage.base import Base
from ai_bridge.storage.database import Database
from ai_bridge.storage.object_store import (
    FileObjectStore,
    ObjectStoreCorruption,
    ObjectStoreNotFound,
)


def setup_services(tmp_path: Path):
    database = Database("sqlite+pysqlite:///" + str(tmp_path / "ers.sqlite"))

    @event.listens_for(database.engine, "connect")
    def enable_foreign_keys(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(database.engine)
    with database.session() as session:
        session.add(ErsCaseCounterModel(counter_name="case", next_value=1))

    case_repository = ErsCaseRepository(database)
    artifact_repository = ErsArtifactRepository(database)
    store = FileObjectStore(tmp_path / "objects")
    service = ErsArtifactService(
        repository=artifact_repository,
        object_store=store,
    )
    return database, case_repository, artifact_repository, store, service


def test_shared_object_store_uses_existing_stage_j_layout_and_deduplicates(tmp_path):
    store = FileObjectStore(tmp_path / "objects")
    content = b"immutable ECU artifact"
    digest = sha256(content).hexdigest()

    first = store.put(content)
    second = store.put(content)

    expected = tmp_path / "objects" / "sha256" / digest[:2] / digest
    assert first.sha256 == digest
    assert first.uri == expected.resolve().as_uri()
    assert second == first
    assert expected.read_bytes() == content
    assert expected.stat().st_mode & 0o222 == 0


def test_shared_object_store_detects_missing_and_corrupt_objects(tmp_path):
    store = FileObjectStore(tmp_path / "objects")
    stored = store.put(b"original")

    with pytest.raises(ObjectStoreNotFound):
        store.read("0" * 64)

    path = store.path_for(stored.sha256)
    path.chmod(0o644)
    path.write_bytes(b"corrupt")

    with pytest.raises(ObjectStoreCorruption):
        store.verify(stored.sha256)


def test_stage_j_content_store_is_compatible_adapter(tmp_path):
    legacy = FileContentStore(tmp_path / "objects")
    content = b"# Existing Knowledge object\n"
    stored = legacy.put(content)

    assert stored.sha256 == sha256(content).hexdigest()
    assert Path(stored.uri.removeprefix("file://")).is_file()
    legacy.verify(stored.uri, stored.sha256)

    again = legacy.put(content)
    assert again == stored


def test_ers_ingest_hashes_server_side_and_filename_never_controls_storage(tmp_path):
    database, cases, artifacts, store, service = setup_services(tmp_path)
    case = cases.create_case(title="Artifact ingest", actor_id="operator")
    content = b"\x00\x01ECU-FLASH\xff"

    result = service.ingest_bytes(
        case_id=case.id,
        artifact_kind="binary",
        created_by="operator",
        content=content,
        media_type="application/octet-stream",
        title="ORI flash",
        original_filename="../../dangerous/original.bin",
    )

    digest = sha256(content).hexdigest()
    assert result.version.object_sha256 == digest
    assert result.version.byte_size == len(content)
    assert result.version.availability == "available"
    assert result.artifact.original_filename == "../../dangerous/original.bin"
    assert store.path_for(digest).name == digest
    assert "original.bin" not in str(store.path_for(digest))
    assert service.read_version(result.version.id) == content
    database.dispose()


def test_ers_same_bytes_share_object_but_keep_distinct_artifact_identity(tmp_path):
    database, cases, artifacts, store, service = setup_services(tmp_path)
    case = cases.create_case(title="Dedup", actor_id="operator")
    content = b"same immutable bytes"

    first = service.ingest_bytes(
        case_id=case.id,
        artifact_kind="binary",
        created_by="operator",
        content=content,
        original_filename="ori.bin",
    )
    second = service.ingest_bytes(
        case_id=case.id,
        artifact_kind="binary",
        created_by="operator",
        content=content,
        original_filename="donor.bin",
    )

    assert first.artifact.id != second.artifact.id
    assert first.version.object_sha256 == second.version.object_sha256
    digest = first.version.object_sha256
    assert digest is not None
    assert store.exists(digest)
    assert len(list((tmp_path / "objects" / "sha256" / digest[:2]).iterdir())) == 1
    database.dispose()


def test_missing_original_records_expected_identity_without_fake_bytes(tmp_path):
    database, cases, artifacts, store, service = setup_services(tmp_path)
    case = cases.create_case(title="Missing original", actor_id="operator")
    digest = "a" * 64

    result = service.declare_missing_original(
        case_id=case.id,
        artifact_kind="binary",
        created_by="operator",
        expected_sha256=digest,
        expected_byte_size=458752,
        original_filename="missing.bin",
    )

    assert result.version.availability == "missing_original"
    assert result.version.object_sha256 == digest
    assert result.version.byte_size == 458752
    assert not store.exists(digest)
    with pytest.raises(ErsArtifactContentUnavailable):
        service.read_version(result.version.id)
    database.dispose()


def test_artifact_versions_are_monotonic_and_content_verified_on_read(tmp_path):
    database, cases, artifacts, store, service = setup_services(tmp_path)
    case = cases.create_case(title="Versions", actor_id="operator")

    first = service.ingest_bytes(
        case_id=case.id,
        artifact_kind="text",
        created_by="operator",
        content=b"v1",
    )
    second = service.append_bytes(first.artifact.id, content=b"v2")
    third = service.append_bytes(
        first.artifact.id,
        content=b"v3",
        parent_artifact_version_id=second.id,
        derivation_type="corrected",
    )

    versions = artifacts.list_versions(first.artifact.id)
    assert [item.version_no for item in versions] == [1, 2, 3]
    assert third.parent_artifact_version_id == second.id
    assert third.derivation_type == "corrected"

    digest = third.object_sha256
    assert digest is not None
    path = store.path_for(digest)
    path.chmod(0o644)
    path.write_bytes(b"tampered")

    with pytest.raises(ErsArtifactContentUnavailable):
        service.read_version(third.id)
    database.dispose()
