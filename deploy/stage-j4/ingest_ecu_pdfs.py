from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess

from ai_bridge.knowledge.content_store import FileContentStore
from ai_bridge.knowledge.pdf_ingestion import (
    PdfIngestRequest,
    PdfKnowledgeIngestor,
    PdfPageChunker,
    PdfTextExtractor,
)
from ai_bridge.knowledge.storage.repository import KnowledgeRepository
from ai_bridge.settings import Settings
from ai_bridge.storage.database import Database


DEFAULT_ROOT = Path(os.environ.get(
    "ECU_REPAIR_KNOWLEDGE_ROOT",
    "/srv/ai-data/knowledge/source-cache/EcuRepairService",
))
SOURCE_URI = "github://autoklinika/EcuRepairService"


def git_value(root: Path, *args: str) -> str:
    return subprocess.check_output(
        ["git", "-C", str(root), *args],
        text=True,
    ).strip()


def validate_read_only_source(root: Path) -> str:
    origin = git_value(root, "remote", "get-url", "origin")
    if "github.com/autoklinika/EcuRepairService" not in origin:
        raise RuntimeError(f"unexpected source origin: {origin}")
    if git_value(root, "status", "--porcelain"):
        raise RuntimeError("EcuRepairService source cache must be clean/read-only")
    return git_value(root, "rev-parse", "HEAD")


def choose_files(root: Path, requested: list[str], limit: int | None) -> list[Path]:
    if requested:
        files = [(root / item).resolve() for item in requested]
        for path in files:
            if root.resolve() not in path.parents or not path.is_file():
                raise RuntimeError(f"invalid source path: {path}")
            if path.suffix.casefold() != ".pdf":
                raise RuntimeError(f"PDF importer accepts only .pdf: {path}")
    else:
        files = sorted(root.rglob("*.pdf"))
    if limit is not None:
        files = files[:limit]
    return files


def extractor(settings: Settings) -> PdfTextExtractor:
    tesseract = settings.knowledge_pdf_tesseract
    return PdfTextExtractor(
        tesseract=str(tesseract) if tesseract.is_file() else None,
        tessdata_prefix=str(settings.knowledge_pdf_tessdata_dir),
        tesseract_lib_dir=str(settings.knowledge_pdf_tesseract_lib_dir),
        ocr_languages=settings.knowledge_pdf_ocr_languages,
        min_text_alnum=settings.knowledge_pdf_ocr_min_alnum,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--path", action="append", default=[])
    parser.add_argument("--limit", type=int)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    root = args.root.resolve()
    commit = validate_read_only_source(root)
    files = choose_files(root, args.path, args.limit)
    if args.dry_run:
        print(json.dumps({
            "mode": "dry-run",
            "source_commit": commit,
            "documents": len(files),
            "paths": [path.relative_to(root).as_posix() for path in files],
        }, ensure_ascii=False, indent=2))
        return

    settings = Settings()
    database = Database(settings.database_url)
    repository = KnowledgeRepository(database)
    ingestor = PdfKnowledgeIngestor(
        repository=repository,
        extractor=extractor(settings),
        chunker=PdfPageChunker(
            max_chars=settings.knowledge_chunk_max_chars,
            profile=settings.knowledge_pdf_chunk_profile,
        ),
        content_store=FileContentStore(settings.knowledge_object_store_dir),
    )

    summary = {
        "documents": 0,
        "new_versions": 0,
        "new_chunks": 0,
        "ocr_pages": 0,
        "pending_jobs": [],
        "source_commit": commit,
    }
    try:
        for path in files:
            rel = path.relative_to(root).as_posix()
            outcome = ingestor.ingest(PdfIngestRequest(
                path=path,
                source_uri=SOURCE_URI,
                document_uri=f"{SOURCE_URI}/{rel}",
                source_revision=commit,
                domain="ecu-repair",
                namespace="ecu-repair",
                index_profile=settings.knowledge_index_profile,
                source_type="documentation",
                source_title="EcuRepairService",
                source_metadata={"repository": "autoklinika/EcuRepairService"},
                document_metadata={"repository_path": rel},
            ))
            summary["documents"] += 1
            summary["new_versions"] += int(outcome.canonical.version_created)
            summary["new_chunks"] += outcome.canonical.chunks_created
            summary["ocr_pages"] += len(outcome.ocr_pages)
            if outcome.canonical.index_job_state in {"pending", "failed"}:
                summary["pending_jobs"].append(outcome.canonical.index_job_id)
            print(json.dumps({
                "path": rel,
                "page_count": outcome.page_count,
                "ocr_pages": list(outcome.ocr_pages),
                "version_created": outcome.canonical.version_created,
                "chunks_created": outcome.canonical.chunks_created,
                "index_job": outcome.canonical.index_job_id,
                "index_state": outcome.canonical.index_job_state,
            }, ensure_ascii=False))
    finally:
        database.dispose()

    print(json.dumps({"summary": summary}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
