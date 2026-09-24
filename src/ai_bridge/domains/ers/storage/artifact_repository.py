from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import func, select

from ai_bridge.storage.database import Database

from .models import (
    ErsArtifactModel,
    ErsArtifactVersionModel,
    ErsCaseModel,
)


ARTIFACT_KINDS = {
    "photo",
    "pdf",
    "binary",
    "log",
    "can_capture",
    "scope_trace",
    "measurement_export",
    "text",
    "other",
}

AVAILABILITY = {"available", "missing_original", "quarantined"}


class ErsArtifactNotFound(KeyError):
    pass


class ErsArtifactCaseNotFound(KeyError):
    pass


@dataclass(frozen=True)
class ErsArtifactSnapshot:
    id: UUID
    case_id: UUID
    ecu_id: UUID | None
    asset_id: UUID | None
    artifact_kind: str
    title: str | None
    role: str | None
    original_filename: str | None
    created_at: datetime
    created_by: str
    metadata: dict


@dataclass(frozen=True)
class ErsArtifactVersionSnapshot:
    id: UUID
    artifact_id: UUID
    version_no: int
    object_sha256: str | None
    byte_size: int
    media_type: str | None
    availability: str
    acquired_at: datetime
    provenance_id: UUID | None
    parent_artifact_version_id: UUID | None
    derivation_type: str | None
    metadata: dict


def _now() -> datetime:
    return datetime.now(timezone.utc)


class ErsArtifactRepository:
    def __init__(self, database: Database) -> None:
        self._database = database

    def create_with_version(
        self,
        *,
        case_id: UUID,
        artifact_kind: str,
        created_by: str,
        object_sha256: str | None,
        byte_size: int,
        availability: str,
        media_type: str | None = None,
        title: str | None = None,
        role: str | None = None,
        original_filename: str | None = None,
        ecu_id: UUID | None = None,
        asset_id: UUID | None = None,
        provenance_id: UUID | None = None,
        acquired_at: datetime | None = None,
        artifact_metadata: dict | None = None,
        version_metadata: dict | None = None,
    ) -> tuple[ErsArtifactSnapshot, ErsArtifactVersionSnapshot]:
        self._validate_header(artifact_kind, created_by)
        self._validate_version(object_sha256, byte_size, availability)

        with self._database.session() as session:
            if session.get(ErsCaseModel, case_id) is None:
                raise ErsArtifactCaseNotFound(str(case_id))

            now = _now()
            artifact = ErsArtifactModel(
                id=uuid4(),
                case_id=case_id,
                ecu_id=ecu_id,
                asset_id=asset_id,
                artifact_kind=artifact_kind,
                title=title,
                role=role,
                original_filename=original_filename,
                created_at=now,
                created_by=created_by.strip(),
                metadata_json={} if artifact_metadata is None else dict(artifact_metadata),
            )
            session.add(artifact)
            session.flush()

            version = ErsArtifactVersionModel(
                id=uuid4(),
                artifact_id=artifact.id,
                version_no=1,
                object_sha256=object_sha256,
                byte_size=byte_size,
                media_type=media_type,
                availability=availability,
                acquired_at=acquired_at or now,
                provenance_id=provenance_id,
                metadata_json={} if version_metadata is None else dict(version_metadata),
            )
            session.add(version)
            session.flush()
            return self._artifact_snapshot(artifact), self._version_snapshot(version)

    def append_version(
        self,
        artifact_id: UUID,
        *,
        object_sha256: str | None,
        byte_size: int,
        availability: str,
        media_type: str | None = None,
        provenance_id: UUID | None = None,
        parent_artifact_version_id: UUID | None = None,
        derivation_type: str | None = None,
        acquired_at: datetime | None = None,
        metadata: dict | None = None,
    ) -> ErsArtifactVersionSnapshot:
        self._validate_version(object_sha256, byte_size, availability)

        with self._database.session() as session:
            artifact = session.scalar(
                select(ErsArtifactModel)
                .where(ErsArtifactModel.id == artifact_id)
                .with_for_update()
            )
            if artifact is None:
                raise ErsArtifactNotFound(str(artifact_id))

            current = session.scalar(
                select(func.max(ErsArtifactVersionModel.version_no)).where(
                    ErsArtifactVersionModel.artifact_id == artifact_id
                )
            )
            version = ErsArtifactVersionModel(
                id=uuid4(),
                artifact_id=artifact_id,
                version_no=int(current or 0) + 1,
                object_sha256=object_sha256,
                byte_size=byte_size,
                media_type=media_type,
                availability=availability,
                acquired_at=acquired_at or _now(),
                provenance_id=provenance_id,
                parent_artifact_version_id=parent_artifact_version_id,
                derivation_type=derivation_type,
                metadata_json={} if metadata is None else dict(metadata),
            )
            session.add(version)
            session.flush()
            return self._version_snapshot(version)

    def get_artifact(self, artifact_id: UUID) -> ErsArtifactSnapshot:
        with self._database.session() as session:
            row = session.get(ErsArtifactModel, artifact_id)
            if row is None:
                raise ErsArtifactNotFound(str(artifact_id))
            return self._artifact_snapshot(row)

    def get_version(self, version_id: UUID) -> ErsArtifactVersionSnapshot:
        with self._database.session() as session:
            row = session.get(ErsArtifactVersionModel, version_id)
            if row is None:
                raise ErsArtifactNotFound(str(version_id))
            return self._version_snapshot(row)

    def list_versions(self, artifact_id: UUID) -> tuple[ErsArtifactVersionSnapshot, ...]:
        with self._database.session() as session:
            if session.get(ErsArtifactModel, artifact_id) is None:
                raise ErsArtifactNotFound(str(artifact_id))
            rows = session.scalars(
                select(ErsArtifactVersionModel)
                .where(ErsArtifactVersionModel.artifact_id == artifact_id)
                .order_by(ErsArtifactVersionModel.version_no)
            ).all()
            return tuple(self._version_snapshot(row) for row in rows)

    @staticmethod
    def _validate_header(artifact_kind: str, created_by: str) -> None:
        if artifact_kind not in ARTIFACT_KINDS:
            raise ValueError("invalid artifact_kind")
        if not created_by.strip():
            raise ValueError("created_by is required")

    @staticmethod
    def _validate_version(
        object_sha256: str | None,
        byte_size: int,
        availability: str,
    ) -> None:
        if availability not in AVAILABILITY:
            raise ValueError("invalid availability")
        if byte_size < 0:
            raise ValueError("byte_size must be >= 0")
        if availability == "available" and object_sha256 is None:
            raise ValueError("available artifact version requires object_sha256")

    @staticmethod
    def _artifact_snapshot(row: ErsArtifactModel) -> ErsArtifactSnapshot:
        return ErsArtifactSnapshot(
            id=row.id,
            case_id=row.case_id,
            ecu_id=row.ecu_id,
            asset_id=row.asset_id,
            artifact_kind=row.artifact_kind,
            title=row.title,
            role=row.role,
            original_filename=row.original_filename,
            created_at=row.created_at,
            created_by=row.created_by,
            metadata=dict(row.metadata_json),
        )

    @staticmethod
    def _version_snapshot(row: ErsArtifactVersionModel) -> ErsArtifactVersionSnapshot:
        return ErsArtifactVersionSnapshot(
            id=row.id,
            artifact_id=row.artifact_id,
            version_no=row.version_no,
            object_sha256=row.object_sha256,
            byte_size=row.byte_size,
            media_type=row.media_type,
            availability=row.availability,
            acquired_at=row.acquired_at,
            provenance_id=row.provenance_id,
            parent_artifact_version_id=row.parent_artifact_version_id,
            derivation_type=row.derivation_type,
            metadata=dict(row.metadata_json),
        )
