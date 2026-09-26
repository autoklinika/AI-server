from ai_bridge.domains.ers.artifacts import ErsArtifactService
from ai_bridge.domains.ers.storage.artifact_repository import ErsArtifactRepository
from ai_bridge.domains.ers.storage.models import ErsCaseCounterModel
from ai_bridge.domains.ers.storage.repository import ErsCaseRepository
from ai_bridge.knowledge.canonical import (
    chunk_record,
    document_record,
    document_version_record,
    source_record,
)
from ai_bridge.knowledge.storage.repository import KnowledgeDocumentSnapshot
from ai_bridge.platform.source_provenance import resolve_source_provenance
from ai_bridge.storage.base import Base
from ai_bridge.storage.database import Database
from ai_bridge.storage.object_store import FileObjectStore


def test_case_source_provenance_distinguishes_exact_note_from_related_originals(tmp_path):
    database = Database("sqlite+pysqlite:///" + str(tmp_path / "provenance.sqlite"))
    Base.metadata.create_all(database.engine)
    with database.session() as session:
        session.add(ErsCaseCounterModel(counter_name="case", next_value=1))

    case = ErsCaseRepository(database).create_case(
        title="Hatz workshop case",
        actor_id="operator",
        legacy_case_code="CASE-LEGACY-HATZ",
    )
    store = FileObjectStore(tmp_path / "objects")
    artifacts = ErsArtifactService(
        repository=ErsArtifactRepository(database),
        object_store=store,
    )

    note_raw = b"# Diagnosis\n\nRoot cause: damaged wire."
    note = artifacts.ingest_bytes(
        case_id=case.id,
        artifact_kind="text",
        created_by="operator",
        content=note_raw,
        media_type="text/markdown",
        title="diagnosis",
        role="diagnosis",
        original_filename="diagnosis.md",
        artifact_metadata={
            "legacy_source_kind": "repo_file",
            "legacy_source_path": "diagnosis.md",
        },
    )
    photo = artifacts.ingest_bytes(
        case_id=case.id,
        artifact_kind="photo",
        created_by="operator",
        content=b"\xff\xd8\xffphoto",
        media_type="image/jpeg",
        title="root_cause",
        role="root_cause",
        original_filename="root-cause.jpg",
        artifact_metadata={
            "legacy_source_kind": "local_original",
            "legacy_source_path": "local-originals/root-cause.jpg",
        },
    )

    source = source_record(
        domain="ecu-repair",
        namespace="ecu-repair",
        source_type="github",
        uri="github://autoklinika/EcuRepairService",
        title="EcuRepairService",
    )
    document = document_record(
        source,
        uri=(
            "github://autoklinika/EcuRepairService/"
            "cases/CASE-LEGACY-HATZ/diagnosis.md"
        ),
        title="CASE-LEGACY-HATZ — diagnosis",
        media_type="text/markdown",
        metadata={
            "repository_path": "cases/CASE-LEGACY-HATZ/diagnosis.md",
        },
    )
    stored_note = store.verify(note.version.object_sha256)
    version = document_version_record(
        document,
        content_sha256=stored_note.sha256,
        byte_size=stored_note.byte_size,
        storage_uri=stored_note.uri,
        source_revision="test",
    )
    chunk = chunk_record(
        version,
        ordinal=0,
        text="Root cause: damaged wire.",
        locator={"section": "Root cause"},
    )
    snapshot = KnowledgeDocumentSnapshot(
        source=source,
        document=document,
        version=version,
        chunks=(chunk,),
    )

    provenance = resolve_source_provenance(database, snapshot)

    assert provenance["case"]["case_code"] == case.case_code
    assert provenance["direct_original"]["role"] == "workshop_note"
    assert provenance["exact_ers_artifact"]["version_id"] == str(note.version.id)
    assert provenance["exact_ers_artifact"]["same_bytes_as_document"] is True
    assert provenance["exact_ers_artifact"]["relationship"] == "exact_ers_record"
    assert [item["version_id"] for item in provenance["related_originals"]] == [
        str(photo.version.id)
    ]
    assert provenance["related_originals"][0]["relationship"] == "same_case_original"
    assert provenance["provenance_policy"] == {
        "exact_relationships_only": True,
        "case_related_originals_are_not_claimed_as_exact_evidence": True,
    }

    database.dispose()
