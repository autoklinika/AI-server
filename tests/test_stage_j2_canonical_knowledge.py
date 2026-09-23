import pytest

from ai_bridge.knowledge.canonical import (
    chunk_record,
    document_record,
    document_version_record,
    sha256_text,
    source_record,
)


def sample_source():
    return source_record(
        domain="ecu-repair",
        namespace="ecu-repair",
        source_type="github",
        uri="github://autoklinika/EcuRepairService",
        title="EcuRepairService",
        acl_policy_id="knowledge-internal",
        metadata={"repository": "autoklinika/EcuRepairService"},
    )


def test_canonical_ids_are_deterministic_and_backend_neutral():
    first = sample_source()
    second = sample_source()

    assert first.source_id == second.source_id
    assert first.source_id.startswith("ksrc_")
    assert first.acl_policy_id == "knowledge-internal"
    assert "qdrant" not in repr(first).lower()

    different_domain = source_record(
        domain="wvc",
        namespace="wvc",
        source_type="github",
        uri=first.uri,
    )
    assert different_domain.source_id != first.source_id

    with pytest.raises(TypeError):
        first.metadata["repository"] = "changed"

def test_document_version_is_bound_to_exact_content_and_source_revision():
    source = sample_source()
    document = document_record(
        source,
        uri="github://autoklinika/EcuRepairService/cases/CASE-0001/diagnosis.md",
        title="CASE-0001 diagnosis",
        media_type="text/markdown",
        language="pl",
    )
    content = "SPN 107 FMI 3 diagnosis"
    version = document_version_record(
        document,
        content_sha256=sha256_text(content),
        byte_size=len(content.encode("utf-8")),
        storage_uri="file:///srv/ai-data/knowledge/source-cache/diagnosis.md",
        source_revision="0ee98b94705b691d7347c8a6a5676ac63159e359",
    )

    assert version.version_id.startswith("kver_")
    assert version.document_id == document.document_id
    assert version.source_revision == "0ee98b94705b691d7347c8a6a5676ac63159e359"

    changed = document_version_record(
        document,
        content_sha256=sha256_text(content + " changed"),
        byte_size=len((content + " changed").encode("utf-8")),
        storage_uri=version.storage_uri,
        source_revision="next-revision",
    )
    assert changed.version_id != version.version_id


def test_chunk_identity_is_reproducible_and_preserves_locator():
    source = sample_source()
    document = document_record(
        source,
        uri="github://autoklinika/EcuRepairService/engines/hatz/3H50TICD/PINOUT_WORKSHOP.md",
        title="Hatz C81 workshop pinout",
        media_type="text/markdown",
    )
    text = "K82 — AFDPS signal"
    version = document_version_record(
        document,
        content_sha256=sha256_text(text),
        byte_size=len(text),
        storage_uri="file:///snapshot/PINOUT_WORKSHOP.md",
    )

    a = chunk_record(version, ordinal=4, text=text, locator={"section": "AFDPS"})
    b = chunk_record(version, ordinal=4, text=text, locator={"section": "AFDPS"})

    assert a.chunk_id == b.chunk_id
    assert a.text_sha256 == sha256_text(text)
    assert a.locator["section"] == "AFDPS"

    assert chunk_record(version, ordinal=5, text=text).chunk_id != a.chunk_id
    assert chunk_record(version, ordinal=4, text=text + "!").chunk_id != a.chunk_id


def test_invalid_canonical_records_fail_closed():
    source = sample_source()
    document = document_record(
        source,
        uri="repo://document.md",
        title="Document",
        media_type="text/markdown",
    )

    with pytest.raises(ValueError, match="SHA-256"):
        document_version_record(
            document,
            content_sha256="not-a-sha",
            byte_size=1,
            storage_uri="file:///document.md",
        )

    version = document_version_record(
        document,
        content_sha256=sha256_text("ok"),
        byte_size=2,
        storage_uri="file:///document.md",
    )
    with pytest.raises(ValueError, match="ordinal"):
        chunk_record(version, ordinal=-1, text="bad")

    from ai_bridge.knowledge.canonical import KnowledgeChunkRecord

    with pytest.raises(ValueError, match="does not match"):
        KnowledgeChunkRecord(
            chunk_id="kchk_bad",
            version_id=version.version_id,
            ordinal=0,
            text="actual",
            text_sha256=sha256_text("different"),
        )
