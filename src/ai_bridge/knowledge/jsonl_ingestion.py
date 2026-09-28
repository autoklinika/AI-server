from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Mapping

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


JSONL_CHUNK_PROFILE = "jsonl-record-v1"


@dataclass(frozen=True)
class JsonlIngestRequest:
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
class JsonlIngestOutcome:
    canonical: KnowledgeIngestResult
    content_sha256: str
    document_uri: str
    source_revision: str
    record_count: int
    chunk_profile: str = JSONL_CHUNK_PROFILE


def _record_text(record: Mapping[str, Any]) -> str:
    keys = list(record)
    ordered = ([key for key in ("id", "source_id", "topic", "subtopic") if key in record]
               + sorted(key for key in keys if key not in {"id", "source_id", "topic", "subtopic"}))
    lines = []
    for key in ordered:
        value = record[key]
        rendered = json.dumps(value, ensure_ascii=False, sort_keys=True) if isinstance(
            value, (dict, list)
        ) else str(value)
        lines.append(f"{key}: {rendered}")
    return "\n".join(lines)


@dataclass(frozen=True)
class JsonlKnowledgeIngestor:
    repository: KnowledgeRepository
    content_store: FileContentStore

    def ingest(self, request: JsonlIngestRequest) -> JsonlIngestOutcome:
        path = request.path.resolve()
        if not path.is_file():
            raise FileNotFoundError(path)
        raw_bytes = path.read_bytes()
        try:
            raw = raw_bytes.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError(f"JSONL source is not UTF-8: {path}") from exc
        rows = []
        seen_ids: set[str] = set()
        for line_no, line in enumerate(raw.splitlines(), 1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_no}: invalid JSON") from exc
            if not isinstance(record, dict):
                raise ValueError(f"{path}:{line_no}: record must be object")
            record_id = record.get("id")
            if not isinstance(record_id, str) or not record_id.strip():
                raise ValueError(f"{path}:{line_no}: non-empty string id required")
            if record_id in seen_ids:
                raise ValueError(f"{path}:{line_no}: duplicate id {record_id}")
            seen_ids.add(record_id)
            rows.append((line_no, record_id, record))

        if not rows:
            raise ValueError("cannot ingest empty JSONL")

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
        title = path.stem.replace("_", " ")
        document = document_record(
            source,
            uri=request.document_uri,
            title=title,
            media_type="application/x-ndjson",
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
            metadata={"ingest_format": "jsonl", "record_count": len(rows)},
        )
        chunks = tuple(
            chunk_record(
                version,
                ordinal=ordinal,
                text=_record_text(record),
                chunk_profile=JSONL_CHUNK_PROFILE,
                locator={"record_id": record_id, "line": line_no},
                metadata={"record_id": record_id},
            )
            for ordinal, (line_no, record_id, record) in enumerate(rows)
        )

        result = self.repository.ingest(
            source=source,
            document=document,
            version=version,
            chunks=chunks,
            index_profile=request.index_profile,
        )
        return JsonlIngestOutcome(
            canonical=result,
            content_sha256=stored.sha256,
            document_uri=request.document_uri,
            source_revision=request.source_revision,
            record_count=len(chunks),
        )
