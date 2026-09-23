from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
import re
import subprocess
import tempfile
from typing import Mapping, Any

from ai_bridge.knowledge.canonical import (
    chunk_record,
    document_record,
    document_version_record,
    source_record,
)
from ai_bridge.knowledge.content_store import FileContentStore
from ai_bridge.knowledge.storage.repository import (
    KnowledgeIngestResult,
    KnowledgeRepository,
)


_ALNUM = re.compile(r"[A-Za-z0-9]")


@dataclass(frozen=True)
class PdfPage:
    page: int
    text: str
    extraction_method: str


@dataclass(frozen=True)
class PdfExtraction:
    title: str
    page_count: int
    pages: tuple[PdfPage, ...]
    ocr_pages: tuple[int, ...]


@dataclass(frozen=True)
class PdfTextExtractor:
    pdftotext: str = "/usr/bin/pdftotext"
    pdfinfo: str = "/usr/bin/pdfinfo"
    pdftocairo: str = "/usr/bin/pdftocairo"
    tesseract: str | None = None
    tessdata_prefix: str | None = None
    tesseract_lib_dir: str | None = None
    ocr_languages: str = "eng+pol"
    min_text_alnum: int = 80
    ocr_dpi: int = 200

    def extract(self, path: Path) -> PdfExtraction:
        path = path.resolve()
        if not path.is_file():
            raise FileNotFoundError(path)
        page_count, title = self._pdf_info(path)
        text = self._run_text(path)
        raw_pages = text.split("\f")
        if raw_pages and not raw_pages[-1].strip():
            raw_pages.pop()
        if len(raw_pages) < page_count:
            raw_pages.extend("" for _ in range(page_count - len(raw_pages)))
        elif len(raw_pages) > page_count:
            raw_pages = raw_pages[:page_count]

        pages: list[PdfPage] = []
        ocr_pages: list[int] = []
        for index in range(page_count):
            page_number = index + 1
            extracted = raw_pages[index].strip()
            method = "pdftotext"
            if self._needs_ocr(extracted) and self.tesseract:
                ocr = self._ocr_page(path, page_number)
                if self._quality(ocr) > self._quality(extracted):
                    if extracted:
                        extracted = (
                            extracted.strip()
                            + "\n\n[OCR fallback]\n"
                            + ocr.strip()
                        )
                        method = "pdftotext+ocr-tesseract"
                    else:
                        extracted = ocr.strip()
                        method = "ocr-tesseract"
                    ocr_pages.append(page_number)
            if extracted:
                pages.append(PdfPage(
                    page=page_number,
                    text=extracted,
                    extraction_method=method,
                ))

        if not pages:
            raise ValueError("PDF contains no extractable text")
        return PdfExtraction(
            title=title or path.stem,
            page_count=page_count,
            pages=tuple(pages),
            ocr_pages=tuple(ocr_pages),
        )

    def _pdf_info(self, path: Path) -> tuple[int, str | None]:
        result = subprocess.run(
            [self.pdfinfo, str(path)],
            check=True,
            capture_output=True,
            text=True,
        )
        pages: int | None = None
        title: str | None = None
        for line in result.stdout.splitlines():
            if line.startswith("Pages:"):
                pages = int(line.split(":", 1)[1].strip())
            elif line.startswith("Title:"):
                value = line.split(":", 1)[1].strip()
                title = value or None
        if not pages:
            raise ValueError("pdfinfo did not report a valid page count")
        return pages, title

    def _run_text(self, path: Path) -> str:
        result = subprocess.run(
            [self.pdftotext, "-layout", "-enc", "UTF-8", str(path), "-"],
            check=True,
            capture_output=True,
        )
        return result.stdout.decode("utf-8", errors="replace")

    def _needs_ocr(self, text: str) -> bool:
        return self._quality(text) < self.min_text_alnum

    @staticmethod
    def _quality(text: str) -> int:
        return len(_ALNUM.findall(text))

    def _ocr_page(self, path: Path, page: int) -> str:
        if not self.tesseract:
            return ""
        with tempfile.TemporaryDirectory(prefix="knowledge-ocr-") as tmp:
            prefix = Path(tmp) / "page"
            subprocess.run(
                [
                    self.pdftocairo,
                    "-f", str(page),
                    "-l", str(page),
                    "-png",
                    "-singlefile",
                    "-r", str(self.ocr_dpi),
                    str(path),
                    str(prefix),
                ],
                check=True,
                capture_output=True,
            )
            image = prefix.with_suffix(".png")
            env = dict(os.environ)
            if self.tessdata_prefix:
                env["TESSDATA_PREFIX"] = self.tessdata_prefix
            if self.tesseract_lib_dir:
                current = env.get("LD_LIBRARY_PATH", "")
                env["LD_LIBRARY_PATH"] = (
                    self.tesseract_lib_dir
                    + (":" + current if current else "")
                )
            result = subprocess.run(
                [
                    self.tesseract,
                    str(image),
                    "stdout",
                    "-l", self.ocr_languages,
                    "--psm", "6",
                ],
                check=True,
                capture_output=True,
                env=env,
            )
            return result.stdout.decode("utf-8", errors="replace")


@dataclass(frozen=True)
class PdfChunkDraft:
    ordinal: int
    page: int
    extraction_method: str
    text: str


@dataclass(frozen=True)
class PdfPageChunker:
    max_chars: int = 2400
    profile: str = "pdf-page-2400-v1"

    def __post_init__(self) -> None:
        if self.max_chars < 256:
            raise ValueError("max_chars must be >= 256")
        if not self.profile.strip():
            raise ValueError("chunk profile is required")

    def split(self, extraction: PdfExtraction) -> tuple[PdfChunkDraft, ...]:
        chunks: list[PdfChunkDraft] = []
        for page in extraction.pages:
            header = f"Document: {extraction.title}\nPage: {page.page}\n\n"
            body_limit = max(128, self.max_chars - len(header))
            units = self._units(page.text, body_limit)
            for unit in units:
                chunks.append(PdfChunkDraft(
                    ordinal=len(chunks),
                    page=page.page,
                    extraction_method=page.extraction_method,
                    text=(header + unit).strip(),
                ))
        if not chunks:
            raise ValueError("PDF chunker produced no chunks")
        return tuple(chunks)

    @staticmethod
    def _units(text: str, max_chars: int) -> tuple[str, ...]:
        paragraphs = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
        if not paragraphs:
            paragraphs = [text.strip()]
        result: list[str] = []
        buffer: list[str] = []
        for paragraph in paragraphs:
            pieces = (
                [paragraph[start:start + max_chars] for start in range(0, len(paragraph), max_chars)]
                if len(paragraph) > max_chars
                else [paragraph]
            )
            for piece in pieces:
                candidate = "\n\n".join(buffer + [piece])
                if buffer and len(candidate) > max_chars:
                    result.append("\n\n".join(buffer).strip())
                    buffer = [piece]
                else:
                    buffer.append(piece)
        if buffer:
            result.append("\n\n".join(buffer).strip())
        return tuple(item for item in result if item)


@dataclass(frozen=True)
class PdfIngestRequest:
    path: Path
    source_uri: str
    document_uri: str
    source_revision: str
    domain: str
    namespace: str
    index_profile: str
    source_type: str = "documentation"
    language: str | None = None
    source_title: str | None = None
    acl_policy_id: str | None = None
    source_metadata: Mapping[str, Any] | None = None
    document_metadata: Mapping[str, Any] | None = None


@dataclass(frozen=True)
class PdfIngestOutcome:
    canonical: KnowledgeIngestResult
    content_sha256: str
    page_count: int
    ocr_pages: tuple[int, ...]
    chunk_count: int
    chunk_profile: str


@dataclass(frozen=True)
class PdfKnowledgeIngestor:
    repository: KnowledgeRepository
    extractor: PdfTextExtractor
    chunker: PdfPageChunker
    content_store: FileContentStore

    def ingest(self, request: PdfIngestRequest) -> PdfIngestOutcome:
        path = request.path.resolve()
        raw_bytes = path.read_bytes()
        stored = self.content_store.put(raw_bytes)
        extraction = self.extractor.extract(path)

        source = source_record(
            domain=request.domain,
            namespace=request.namespace,
            source_type=request.source_type,
            uri=request.source_uri,
            title=request.source_title,
            acl_policy_id=request.acl_policy_id,
            metadata={} if request.source_metadata is None else request.source_metadata,
        )
        document = document_record(
            source,
            uri=request.document_uri,
            title=extraction.title,
            media_type="application/pdf",
            language=request.language,
            acl_policy_id=request.acl_policy_id,
            metadata={} if request.document_metadata is None else request.document_metadata,
        )
        version = document_version_record(
            document,
            content_sha256=stored.sha256,
            byte_size=stored.byte_size,
            storage_uri=stored.uri,
            source_revision=request.source_revision,
            metadata={
                "ingest_format": "pdf",
                "page_count": extraction.page_count,
                "ocr_pages": list(extraction.ocr_pages),
                "extractor": "poppler+tesseract-v1",
            },
        )
        drafts = self.chunker.split(extraction)
        chunks = tuple(
            chunk_record(
                version,
                ordinal=draft.ordinal,
                text=draft.text,
                chunk_profile=self.chunker.profile,
                locator={
                    "page": draft.page,
                    "extraction_method": draft.extraction_method,
                },
            )
            for draft in drafts
        )
        result = self.repository.ingest(
            source=source,
            document=document,
            version=version,
            chunks=chunks,
            index_profile=request.index_profile,
        )
        return PdfIngestOutcome(
            canonical=result,
            content_sha256=stored.sha256,
            page_count=extraction.page_count,
            ocr_pages=extraction.ocr_pages,
            chunk_count=len(chunks),
            chunk_profile=self.chunker.profile,
        )
