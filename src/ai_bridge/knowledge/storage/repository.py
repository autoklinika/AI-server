from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable

from sqlalchemy import select

from ai_bridge.knowledge.canonical import (
    KnowledgeChunkRecord,
    KnowledgeDocumentRecord,
    KnowledgeDocumentVersionRecord,
    KnowledgeSourceRecord,
    stable_id,
)
from ai_bridge.storage.database import Database

from .models import (
    KnowledgeChunkModel,
    KnowledgeDocumentModel,
    KnowledgeDocumentVersionModel,
    KnowledgeIndexJobModel,
    KnowledgeSourceModel,
)


class KnowledgeIdentityConflict(RuntimeError):
    """Stable canonical ID already exists with conflicting identity fields."""


@dataclass(frozen=True)
class KnowledgeIngestResult:
    source_created: bool
    document_created: bool
    version_created: bool
    current_changed: bool
    chunks_created: int
    index_job_id: str
    index_job_state: str


@dataclass(frozen=True)
class CanonicalSearchChunk:
    chunk_id: str
    text: str
    domain: str
    namespace: str
    source_type: str
    source_uri: str
    source_title: str | None
    metadata: dict


@dataclass(frozen=True)
class KnowledgeIndexWorkItem:
    job_id: str
    document_id: str
    version_id: str
    chunk_profile: str
    index_profile: str
    source: KnowledgeSourceRecord
    document: KnowledgeDocumentRecord
    version: KnowledgeDocumentVersionRecord
    chunks: tuple[KnowledgeChunkRecord, ...]


def _now() -> datetime:
    return datetime.now(timezone.utc)


class KnowledgeRepository:
    def __init__(self, database: Database) -> None:
        self._database = database

    def ingest(
        self,
        *,
        source: KnowledgeSourceRecord,
        document: KnowledgeDocumentRecord,
        version: KnowledgeDocumentVersionRecord,
        chunks: Iterable[KnowledgeChunkRecord],
        index_profile: str,
    ) -> KnowledgeIngestResult:
        chunk_list = tuple(chunks)
        if document.source_id != source.source_id:
            raise ValueError("document/source identity mismatch")
        if version.document_id != document.document_id:
            raise ValueError("version/document identity mismatch")
        if not chunk_list:
            raise ValueError("ingestion requires at least one chunk")
        profiles = {chunk.chunk_profile for chunk in chunk_list}
        if len(profiles) != 1:
            raise ValueError("all chunks in one ingestion must use one chunk profile")
        if any(chunk.version_id != version.version_id for chunk in chunk_list):
            raise ValueError("chunk/version identity mismatch")
        ordinals = [chunk.ordinal for chunk in chunk_list]
        if ordinals != list(range(len(chunk_list))):
            raise ValueError("chunk ordinals must be contiguous from zero")
        if not index_profile.strip():
            raise ValueError("index_profile is required")
        chunk_profile = chunk_list[0].chunk_profile

        with self._database.session() as session:
            existing_source = session.get(KnowledgeSourceModel, source.source_id)
            source_created = existing_source is None
            if existing_source is None:
                existing_source = KnowledgeSourceModel(
                    source_id=source.source_id,
                    domain=source.domain,
                    namespace=source.namespace,
                    source_type=source.source_type,
                    uri=source.uri,
                    title=source.title,
                    acl_policy_id=source.acl_policy_id,
                    metadata_json=dict(source.metadata),
                )
                session.add(existing_source)
            else:
                self._validate_source_identity(existing_source, source)
                existing_source.title = source.title
                existing_source.acl_policy_id = source.acl_policy_id
                existing_source.metadata_json = dict(source.metadata)
                existing_source.updated_at = _now()

            existing_document = session.get(KnowledgeDocumentModel, document.document_id)
            document_created = existing_document is None
            if existing_document is None:
                existing_document = KnowledgeDocumentModel(
                    document_id=document.document_id,
                    source_id=document.source_id,
                    uri=document.uri,
                    title=document.title,
                    media_type=document.media_type,
                    language=document.language,
                    acl_policy_id=document.acl_policy_id,
                    metadata_json=dict(document.metadata),
                )
                session.add(existing_document)
            else:
                self._validate_document_identity(existing_document, document)
                existing_document.title = document.title
                existing_document.media_type = document.media_type
                existing_document.language = document.language
                existing_document.acl_policy_id = document.acl_policy_id
                existing_document.metadata_json = dict(document.metadata)
                existing_document.updated_at = _now()

            existing_version = session.get(
                KnowledgeDocumentVersionModel, version.version_id
            )
            version_created = existing_version is None
            if existing_version is None:
                existing_version = KnowledgeDocumentVersionModel(
                    version_id=version.version_id,
                    document_id=version.document_id,
                    content_sha256=version.content_sha256,
                    byte_size=version.byte_size,
                    storage_uri=version.storage_uri,
                    source_revision=version.source_revision,
                    metadata_json=dict(version.metadata),
                )
                session.add(existing_version)
            else:
                self._validate_version_identity(existing_version, version)

            existing_chunks = tuple(
                session.scalars(
                    select(KnowledgeChunkModel)
                    .where(
                        KnowledgeChunkModel.version_id == version.version_id,
                        KnowledgeChunkModel.chunk_profile == chunk_profile,
                    )
                    .order_by(KnowledgeChunkModel.ordinal)
                ).all()
            )
            chunks_created = 0
            if existing_chunks:
                self._validate_chunks(existing_chunks, chunk_list)
            else:
                for chunk in chunk_list:
                    session.add(KnowledgeChunkModel(
                        chunk_id=chunk.chunk_id,
                        version_id=chunk.version_id,
                        chunk_profile=chunk.chunk_profile,
                        ordinal=chunk.ordinal,
                        text=chunk.text,
                        text_sha256=chunk.text_sha256,
                        locator=dict(chunk.locator),
                        metadata_json=dict(chunk.metadata),
                    ))
                chunks_created = len(chunk_list)

            current_changed = existing_document.current_version_id != version.version_id
            existing_document.current_version_id = version.version_id
            existing_document.updated_at = _now()

            if current_changed:
                stale_jobs = session.scalars(
                    select(KnowledgeIndexJobModel).where(
                        KnowledgeIndexJobModel.document_id == document.document_id,
                        KnowledgeIndexJobModel.version_id != version.version_id,
                        KnowledgeIndexJobModel.state.in_(("pending", "failed")),
                    )
                ).all()
                for stale in stale_jobs:
                    stale.state = "superseded"
                    stale.updated_at = _now()

            job_id = stable_id(
                "kjob", version.version_id, chunk_profile, index_profile
            )
            job = session.get(KnowledgeIndexJobModel, job_id)
            if job is None:
                job = KnowledgeIndexJobModel(
                    job_id=job_id,
                    document_id=document.document_id,
                    version_id=version.version_id,
                    chunk_profile=chunk_profile,
                    index_profile=index_profile,
                    state="pending",
                )
                session.add(job)
            elif current_changed and job.state in {"completed", "superseded"}:
                job.state = "pending"
                job.last_error = None
                job.completed_at = None
                job.updated_at = _now()

            return KnowledgeIngestResult(
                source_created=source_created,
                document_created=document_created,
                version_created=version_created,
                current_changed=current_changed,
                chunks_created=chunks_created,
                index_job_id=job_id,
                index_job_state=job.state,
            )

    def get_index_work(self, job_id: str) -> KnowledgeIndexWorkItem:
        with self._database.session() as session:
            job = session.get(KnowledgeIndexJobModel, job_id)
            if job is None:
                raise KeyError(job_id)
            document = session.get(KnowledgeDocumentModel, job.document_id)
            version = session.get(KnowledgeDocumentVersionModel, job.version_id)
            if document is None or version is None:
                raise KnowledgeIdentityConflict("index job lost canonical parent")
            source = session.get(KnowledgeSourceModel, document.source_id)
            if source is None:
                raise KnowledgeIdentityConflict("document lost canonical source")
            rows = tuple(
                session.scalars(
                    select(KnowledgeChunkModel)
                    .where(
                        KnowledgeChunkModel.version_id == job.version_id,
                        KnowledgeChunkModel.chunk_profile == job.chunk_profile,
                    )
                    .order_by(KnowledgeChunkModel.ordinal)
                ).all()
            )
            if not rows:
                raise KnowledgeIdentityConflict("index job has no chunks")
            return KnowledgeIndexWorkItem(
                job_id=job.job_id,
                document_id=job.document_id,
                version_id=job.version_id,
                chunk_profile=job.chunk_profile,
                index_profile=job.index_profile,
                source=self._source_record(source),
                document=self._document_record(document),
                version=self._version_record(version),
                chunks=tuple(self._chunk_record(row) for row in rows),
            )

    def mark_index_running(self, job_id: str) -> bool:
        with self._database.session() as session:
            job = self._require_job(session, job_id)
            document = session.get(KnowledgeDocumentModel, job.document_id)
            if document is None or document.current_version_id != job.version_id:
                job.state = "superseded"
                job.updated_at = _now()
                return False
            if job.state in {"running", "completed", "superseded"}:
                return False
            job.state = "running"
            job.attempts += 1
            job.last_error = None
            job.updated_at = _now()
            return True
    def mark_index_completed(self, job_id: str) -> None:
        with self._database.session() as session:
            job = self._require_job(session, job_id)
            document = session.get(KnowledgeDocumentModel, job.document_id)
            if document is None or document.current_version_id != job.version_id:
                job.state = "superseded"
                job.completed_at = None
            else:
                job.state = "completed"
                job.completed_at = _now()
                job.last_error = None
            job.updated_at = _now()

    def mark_index_failed(self, job_id: str, error: str) -> None:
        with self._database.session() as session:
            job = self._require_job(session, job_id)
            job.state = "failed"
            job.last_error = error[:4000]
            job.completed_at = None
            job.updated_at = _now()

    def current_chunks(
        self,
        *,
        domain: str,
        namespaces: tuple[str, ...] = (),
        source_types: tuple[str, ...] = (),
        limit: int = 5000,
    ) -> tuple[CanonicalSearchChunk, ...]:
        if not 1 <= limit <= 50000:
            raise ValueError("limit must be between 1 and 50000")
        statement = (
            select(KnowledgeChunkModel, KnowledgeDocumentModel, KnowledgeSourceModel)
            .join(
                KnowledgeDocumentModel,
                KnowledgeDocumentModel.current_version_id == KnowledgeChunkModel.version_id,
            )
            .join(
                KnowledgeSourceModel,
                KnowledgeSourceModel.source_id == KnowledgeDocumentModel.source_id,
            )
            .where(KnowledgeSourceModel.domain == domain)
        )
        if namespaces:
            statement = statement.where(KnowledgeSourceModel.namespace.in_(namespaces))
        if source_types:
            statement = statement.where(KnowledgeSourceModel.source_type.in_(source_types))
        statement = statement.order_by(
            KnowledgeDocumentModel.document_id,
            KnowledgeChunkModel.ordinal,
        ).limit(limit)

        with self._database.session() as session:
            rows = session.execute(statement).all()
            return tuple(self._search_chunk(*row) for row in rows)

    def pending_job_ids(
        self, *, limit: int = 100, index_profile: str | None = None
    ) -> tuple[str, ...]:
        if not 1 <= limit <= 1000:
            raise ValueError("limit must be between 1 and 1000")
        statement = select(KnowledgeIndexJobModel.job_id).where(
            KnowledgeIndexJobModel.state.in_(("pending", "failed"))
        )
        if index_profile is not None:
            statement = statement.where(
                KnowledgeIndexJobModel.index_profile == index_profile
            )
        statement = statement.order_by(
            KnowledgeIndexJobModel.created_at,
            KnowledgeIndexJobModel.job_id,
        ).limit(limit)
        with self._database.session() as session:
            return tuple(session.scalars(statement).all())

    @staticmethod
    def _search_chunk(
        chunk: KnowledgeChunkModel,
        document: KnowledgeDocumentModel,
        source: KnowledgeSourceModel,
    ) -> CanonicalSearchChunk:
        metadata = {
            **dict(source.metadata_json),
            **dict(document.metadata_json),
            **dict(chunk.metadata_json),
            **dict(chunk.locator),
            "source_id": source.source_id,
            "document_id": document.document_id,
            "version_id": chunk.version_id,
            "chunk_id": chunk.chunk_id,
            "chunk_profile": chunk.chunk_profile,
            "chunk_ordinal": chunk.ordinal,
        }
        return CanonicalSearchChunk(
            chunk_id=chunk.chunk_id,
            text=chunk.text,
            domain=source.domain,
            namespace=source.namespace,
            source_type=source.source_type,
            source_uri=document.uri,
            source_title=document.title,
            metadata=metadata,
        )

    @staticmethod
    def _require_job(session, job_id: str) -> KnowledgeIndexJobModel:
        job = session.get(KnowledgeIndexJobModel, job_id)
        if job is None:
            raise KeyError(job_id)
        return job

    @staticmethod
    def _validate_source_identity(row, record: KnowledgeSourceRecord) -> None:
        actual = (row.domain, row.namespace, row.source_type, row.uri)
        expected = (record.domain, record.namespace, record.source_type, record.uri)
        if actual != expected:
            raise KnowledgeIdentityConflict("source ID maps to conflicting identity")

    @staticmethod
    def _validate_document_identity(row, record: KnowledgeDocumentRecord) -> None:
        if (row.source_id, row.uri) != (record.source_id, record.uri):
            raise KnowledgeIdentityConflict("document ID maps to conflicting identity")

    @staticmethod
    def _validate_version_identity(row, record: KnowledgeDocumentVersionRecord) -> None:
        actual = (row.document_id, row.content_sha256)
        expected = (record.document_id, record.content_sha256)
        if actual != expected:
            raise KnowledgeIdentityConflict("version ID maps to conflicting identity")

    @staticmethod
    def _validate_chunks(rows, records: tuple[KnowledgeChunkRecord, ...]) -> None:
        if len(rows) != len(records):
            raise KnowledgeIdentityConflict("stored chunk set differs from deterministic input")
        for row, record in zip(rows, records, strict=True):
            actual = (row.chunk_id, row.ordinal, row.text_sha256, row.text)
            expected = (
                record.chunk_id,
                record.ordinal,
                record.text_sha256,
                record.text,
            )
            if actual != expected:
                raise KnowledgeIdentityConflict(
                    "stored chunk identity/content differs from deterministic input"
                )

    @staticmethod
    def _source_record(row: KnowledgeSourceModel) -> KnowledgeSourceRecord:
        return KnowledgeSourceRecord(
            source_id=row.source_id, domain=row.domain, namespace=row.namespace,
            source_type=row.source_type, uri=row.uri, title=row.title,
            acl_policy_id=row.acl_policy_id, metadata=row.metadata_json,
        )

    @staticmethod
    def _document_record(row: KnowledgeDocumentModel) -> KnowledgeDocumentRecord:
        return KnowledgeDocumentRecord(
            document_id=row.document_id, source_id=row.source_id, uri=row.uri,
            title=row.title, media_type=row.media_type, language=row.language,
            acl_policy_id=row.acl_policy_id, metadata=row.metadata_json,
        )

    @staticmethod
    def _version_record(row: KnowledgeDocumentVersionModel) -> KnowledgeDocumentVersionRecord:
        return KnowledgeDocumentVersionRecord(
            version_id=row.version_id, document_id=row.document_id,
            content_sha256=row.content_sha256, byte_size=row.byte_size,
            storage_uri=row.storage_uri, source_revision=row.source_revision,
            metadata=row.metadata_json,
        )

    @staticmethod
    def _chunk_record(row: KnowledgeChunkModel) -> KnowledgeChunkRecord:
        return KnowledgeChunkRecord(
            chunk_id=row.chunk_id,
            version_id=row.version_id,
            chunk_profile=row.chunk_profile,
            ordinal=row.ordinal,
            text=row.text,
            text_sha256=row.text_sha256,
            locator=row.locator,
            metadata=row.metadata_json,
        )
