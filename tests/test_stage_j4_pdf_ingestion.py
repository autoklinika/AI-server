from pathlib import Path

from sqlalchemy import event, select

from ai_bridge.knowledge.content_store import FileContentStore
from ai_bridge.knowledge.pdf_ingestion import (
    PdfExtraction,
    PdfIngestRequest,
    PdfKnowledgeIngestor,
    PdfPage,
    PdfPageChunker,
    PdfTextExtractor,
)
from ai_bridge.knowledge.storage.models import KnowledgeChunkModel
from ai_bridge.knowledge.storage.repository import KnowledgeRepository
from ai_bridge.storage.base import Base
from ai_bridge.storage.database import Database


class FakeExtractor:
    def extract(self, path):
        assert path.read_bytes().startswith(b"%PDF")
        return PdfExtraction(
            title="HATZ test manual",
            page_count=2,
            pages=(
                PdfPage(1, "SPN 107 FMI 3 and Bosch 0 281 007 439.", "pdftotext"),
                PdfPage(2, "K82 is the AFDPS signal.", "ocr-tesseract"),
            ),
            ocr_pages=(2,),
        )


def database(tmp_path):
    db = Database("sqlite:///" + str(tmp_path / "knowledge.sqlite"))

    @event.listens_for(db.engine, "connect")
    def enable_fk(conn, _record):
        cursor = conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(db.engine)
    return db


def test_pdf_ingest_preserves_pages_ocr_provenance_and_idempotency(tmp_path: Path):
    db = database(tmp_path)
    repository = KnowledgeRepository(db)
    pdf = tmp_path / "manual.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake fixture bytes")

    ingestor = PdfKnowledgeIngestor(
        repository=repository,
        extractor=FakeExtractor(),
        chunker=PdfPageChunker(max_chars=512, profile="pdf-page-512-test"),
        content_store=FileContentStore(tmp_path / "objects"),
    )
    request = PdfIngestRequest(
        path=pdf,
        source_uri="github://autoklinika/EcuRepairService",
        document_uri="github://autoklinika/EcuRepairService/manual.pdf",
        source_revision="abc123",
        domain="ecu-repair",
        namespace="ecu-repair",
        index_profile="dense-test-v1",
        source_title="EcuRepairService",
    )

    first = ingestor.ingest(request)
    second = ingestor.ingest(request)

    assert first.page_count == 2
    assert first.ocr_pages == (2,)
    assert first.canonical.version_created is True
    assert first.canonical.chunks_created == 2
    assert second.canonical.version_created is False
    assert second.canonical.chunks_created == 0
    assert second.canonical.index_job_id == first.canonical.index_job_id

    with db.session() as session:
        chunks = tuple(session.scalars(
            select(KnowledgeChunkModel).order_by(KnowledgeChunkModel.ordinal)
        ).all())
    assert chunks[0].locator["page"] == 1
    assert chunks[0].locator["extraction_method"] == "pdftotext"
    assert chunks[1].locator["page"] == 2
    assert chunks[1].locator["extraction_method"] == "ocr-tesseract"
    assert chunks[0].chunk_profile == "pdf-page-512-test"

    work = repository.get_index_work(first.canonical.index_job_id)
    stored = Path(work.version.storage_uri.removeprefix("file://"))
    assert stored.read_bytes() == pdf.read_bytes()
    assert work.version.metadata["page_count"] == 2
    assert work.version.metadata["ocr_pages"] == [2]
    db.dispose()


def test_pdf_text_extractor_ocr_gate_is_quality_based():
    extractor = PdfTextExtractor(min_text_alnum=5, tesseract="/fake/tesseract")
    assert extractor._needs_ocr(".. -") is True
    assert extractor._needs_ocr("K82 123") is False


def test_pdf_page_chunker_never_mixes_pages():
    extraction = PdfExtraction(
        title="Manual",
        page_count=2,
        pages=(
            PdfPage(1, "A" * 700, "pdftotext"),
            PdfPage(2, "B" * 700, "ocr-tesseract"),
        ),
        ocr_pages=(2,),
    )
    chunks = PdfPageChunker(max_chars=300, profile="pdf-test").split(extraction)
    assert {chunk.page for chunk in chunks} == {1, 2}
    for chunk in chunks:
        body = chunk.text.split("\n\n", 1)[-1]
        if chunk.page == 1:
            assert "B" not in body
        else:
            assert "A" not in body
