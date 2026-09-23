from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from ai_bridge.storage.base import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class KnowledgeSourceModel(Base):
    __tablename__ = "knowledge_sources"

    source_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    domain: Mapped[str] = mapped_column(String(128), nullable=False)
    namespace: Mapped[str] = mapped_column(String(128), nullable=False)
    source_type: Mapped[str] = mapped_column(String(64), nullable=False)
    uri: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    acl_policy_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    metadata_json: Mapped[dict] = mapped_column("metadata", JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )


class KnowledgeDocumentModel(Base):
    __tablename__ = "knowledge_documents"
    __table_args__ = (
        UniqueConstraint("source_id", "uri", name="uq_knowledge_document_source_uri"),
        Index("ix_knowledge_document_source", "source_id"),
    )

    document_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    source_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_sources.source_id", ondelete="CASCADE"),
        nullable=False,
    )
    uri: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    media_type: Mapped[str] = mapped_column(String(128), nullable=False)
    language: Mapped[str | None] = mapped_column(String(32), nullable=True)
    acl_policy_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    current_version_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    metadata_json: Mapped[dict] = mapped_column("metadata", JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )


class KnowledgeDocumentVersionModel(Base):
    __tablename__ = "knowledge_document_versions"
    __table_args__ = (
        UniqueConstraint(
            "document_id",
            "content_sha256",
            name="uq_knowledge_version_document_hash",
        ),
        Index("ix_knowledge_version_document", "document_id"),
    )

    version_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    document_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_documents.document_id", ondelete="CASCADE"),
        nullable=False,
    )
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    byte_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    storage_uri: Mapped[str] = mapped_column(Text, nullable=False)
    source_revision: Mapped[str | None] = mapped_column(String(160), nullable=True)
    metadata_json: Mapped[dict] = mapped_column("metadata", JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )


class KnowledgeChunkModel(Base):
    __tablename__ = "knowledge_chunks"
    __table_args__ = (
        UniqueConstraint(
            "version_id",
            "chunk_profile",
            "ordinal",
            name="uq_knowledge_chunk_version_profile_ordinal",
        ),
        Index("ix_knowledge_chunk_version_profile", "version_id", "chunk_profile"),
    )

    chunk_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    version_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_document_versions.version_id", ondelete="CASCADE"),
        nullable=False,
    )
    chunk_profile: Mapped[str] = mapped_column(String(96), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    text_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    locator: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    metadata_json: Mapped[dict] = mapped_column("metadata", JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )


class KnowledgeIndexJobModel(Base):
    __tablename__ = "knowledge_index_jobs"
    __table_args__ = (
        UniqueConstraint(
            "version_id",
            "chunk_profile",
            "index_profile",
            name="uq_knowledge_index_job_version_profiles",
        ),
        Index("ix_knowledge_index_job_state_created", "state", "created_at"),
        Index("ix_knowledge_index_job_document", "document_id"),
    )

    job_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    document_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_documents.document_id", ondelete="CASCADE"),
        nullable=False,
    )
    version_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_document_versions.version_id", ondelete="CASCADE"),
        nullable=False,
    )
    chunk_profile: Mapped[str] = mapped_column(String(96), nullable=False)
    index_profile: Mapped[str] = mapped_column(String(128), nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
