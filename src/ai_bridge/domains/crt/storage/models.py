from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column
from ai_bridge.storage.base import Base
from ai_bridge.domains.ers.storage.models import JSON_TYPE


def utcnow():
    return datetime.now(timezone.utc)


class Audit:
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CRTProject(Audit, Base):
    __tablename__ = "crt_projects"
    external_id: Mapped[str] = mapped_column(String(160), unique=True)


class CRTSession(Audit, Base):
    __tablename__ = "crt_sessions"
    __table_args__ = (
        UniqueConstraint("project_id", "external_id", "manifest_hash"),
        UniqueConstraint("project_id", "external_id", "manifest_version"),
        CheckConstraint("schema_version = 1"),
        CheckConstraint("manifest_version >= 1"),
    )
    project_id: Mapped[UUID] = mapped_column(ForeignKey("crt_projects.id"))
    external_id: Mapped[str] = mapped_column(String(160), index=True)
    schema_version: Mapped[int]
    manifest_version: Mapped[int]
    manifest_hash: Mapped[str] = mapped_column(String(64))
    source_uri: Mapped[str] = mapped_column(String(2048))
    # Immutable canonical manifest; contains only bounded metadata and references.
    manifest: Mapped[dict] = mapped_column(JSON_TYPE)


class CRTArtifact(Audit, Base):
    __tablename__ = "crt_session_artifacts"
    __table_args__ = (UniqueConstraint("session_id", "external_id"), CheckConstraint("byte_size >= 0"))
    session_id: Mapped[UUID] = mapped_column(ForeignKey("crt_sessions.id"))
    external_id: Mapped[str] = mapped_column(String(160))
    source_uri: Mapped[str] = mapped_column(String(2048))
    sha256: Mapped[str] = mapped_column(String(64))
    byte_size: Mapped[int] = mapped_column(BigInteger)
    media_type: Mapped[str] = mapped_column(String(160))
    role: Mapped[str] = mapped_column(String(160))


class CRTLink(Audit, Base):
    __tablename__ = "crt_ers_links"
    __table_args__ = (UniqueConstraint("session_id", "case_id", "role"),)
    session_id: Mapped[UUID] = mapped_column(ForeignKey("crt_sessions.id"))
    case_id: Mapped[UUID] = mapped_column(ForeignKey("ers_cases.id"))
    role: Mapped[str] = mapped_column(String(160))
    actor_id: Mapped[str] = mapped_column(String(160))
    active: Mapped[bool] = mapped_column(default=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CRTFinding(Audit, Base):
    __tablename__ = "crt_ai_findings"
    __table_args__ = (CheckConstraint("status IN ('suggested','to_review')"),)
    session_id: Mapped[UUID] = mapped_column(ForeignKey("crt_sessions.id"), index=True)
    provider: Mapped[str] = mapped_column(String(160))
    model: Mapped[str] = mapped_column(String(160))
    context_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(24), default="suggested")
    payload: Mapped[dict] = mapped_column(JSON_TYPE)
