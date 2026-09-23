from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Any

from ai_bridge.knowledge.canonical import (
    chunk_record,
    document_record,
    document_version_record,
    source_record,
)
from ai_bridge.knowledge.chunking import MarkdownChunker
from ai_bridge.knowledge.content_store import FileContentStore
from ai_bridge.knowledge.storage.repository import (
    KnowledgeIngestResult,
    KnowledgeRepository,
)


@dataclass(frozen=True)
class MarkdownIngestRequest:
    path: Path
    source_uri: str
    document_uri: str
    source_revision: str
    domain: str
    namespace: str
    index_profile: str
    source_type: str = "github"
    source_title: str | None = None
    language: str | None = None
    acl_policy_id: str | None = None
    source_metadata: Mapping[str, Any] | None = None
    document_metadata: Mapping[str, Any] | None = None


@dataclass(frozen=True)
class MarkdownIngestOutcome:
    canonical: KnowledgeIngestResult
    content_sha256: str
    document_uri: str
    source_revision: str
    chunk_count: int
    chunk_profile: str


@dataclass(frozen=True)
class MarkdownKnowledgeIngestor:
    repository: KnowledgeRepository
    chunker: MarkdownChunker
    content_store: FileContentStore

    def ingest(self, request: MarkdownIngestRequest) -> MarkdownIngestOutcome:
        path = request.path.resolve()
        if not path.is_file():
            raise FileNotFoundError(path)
        raw_bytes = path.read_bytes()
        try:
            raw = raw_bytes.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError(f"markdown source is not UTF-8: {path}") from exc
        if not raw.strip():
            raise ValueError("cannot ingest empty markdown")

        title = self._title(raw, path.name)
        stored = self.content_store.put(raw_bytes)

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
            title=title,
            media_type="text/markdown",
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
            metadata={"ingest_format": "markdown"},
        )
        drafts = self.chunker.split(raw, fallback_title=path.name)
        chunks = tuple(
            chunk_record(
                version,
                ordinal=draft.ordinal,
                text=draft.text,
                chunk_profile=self.chunker.profile,
                locator={"section": draft.section},
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
        return MarkdownIngestOutcome(
            canonical=result,
            content_sha256=stored.sha256,
            document_uri=request.document_uri,
            source_revision=request.source_revision,
            chunk_count=len(chunks),
            chunk_profile=self.chunker.profile,
        )

    @staticmethod
    def _title(raw: str, fallback: str) -> str:
        for line in raw.splitlines():
            if line.startswith("#"):
                title = line.lstrip("# ").strip()
                if title:
                    return title
        return fallback
