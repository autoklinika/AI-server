from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from ai_bridge.storage.object_store import (
    ObjectStore,
    ObjectStoreCorruption,
    ObjectStoreNotFound,
    validate_sha256,
)

from .storage.artifact_repository import (
    ErsArtifactRepository,
    ErsArtifactSnapshot,
    ErsArtifactVersionSnapshot,
)


class ErsArtifactContentUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class ErsStoredArtifact:
    artifact: ErsArtifactSnapshot
    version: ErsArtifactVersionSnapshot


class ErsArtifactService:
    def __init__(
        self,
        *,
        repository: ErsArtifactRepository,
        object_store: ObjectStore,
    ) -> None:
        self._repository = repository
        self._object_store = object_store

    def ingest_bytes(
        self,
        *,
        case_id: UUID,
        artifact_kind: str,
        created_by: str,
        content: bytes,
        media_type: str | None = None,
        title: str | None = None,
        role: str | None = None,
        original_filename: str | None = None,
        ecu_id: UUID | None = None,
        asset_id: UUID | None = None,
        provenance_id: UUID | None = None,
        artifact_metadata: dict | None = None,
        version_metadata: dict | None = None,
    ) -> ErsStoredArtifact:
        stored = self._object_store.put(content)
        artifact, version = self._repository.create_with_version(
            case_id=case_id,
            artifact_kind=artifact_kind,
            created_by=created_by,
            object_sha256=stored.sha256,
            byte_size=stored.byte_size,
            availability="available",
            media_type=media_type,
            title=title,
            role=role,
            original_filename=original_filename,
            ecu_id=ecu_id,
            asset_id=asset_id,
            provenance_id=provenance_id,
            artifact_metadata=artifact_metadata,
            version_metadata=version_metadata,
        )
        return ErsStoredArtifact(artifact=artifact, version=version)

    def append_bytes(
        self,
        artifact_id: UUID,
        *,
        content: bytes,
        media_type: str | None = None,
        provenance_id: UUID | None = None,
        parent_artifact_version_id: UUID | None = None,
        derivation_type: str | None = None,
        metadata: dict | None = None,
    ) -> ErsArtifactVersionSnapshot:
        stored = self._object_store.put(content)
        return self._repository.append_version(
            artifact_id,
            object_sha256=stored.sha256,
            byte_size=stored.byte_size,
            availability="available",
            media_type=media_type,
            provenance_id=provenance_id,
            parent_artifact_version_id=parent_artifact_version_id,
            derivation_type=derivation_type,
            metadata=metadata,
        )

    def declare_missing_original(
        self,
        *,
        case_id: UUID,
        artifact_kind: str,
        created_by: str,
        expected_sha256: str,
        expected_byte_size: int,
        media_type: str | None = None,
        title: str | None = None,
        role: str | None = None,
        original_filename: str | None = None,
        ecu_id: UUID | None = None,
        asset_id: UUID | None = None,
        provenance_id: UUID | None = None,
        metadata: dict | None = None,
    ) -> ErsStoredArtifact:
        validate_sha256(expected_sha256)
        if expected_byte_size < 0:
            raise ValueError("expected_byte_size must be >= 0")

        artifact, version = self._repository.create_with_version(
            case_id=case_id,
            artifact_kind=artifact_kind,
            created_by=created_by,
            object_sha256=expected_sha256,
            byte_size=expected_byte_size,
            availability="missing_original",
            media_type=media_type,
            title=title,
            role=role,
            original_filename=original_filename,
            ecu_id=ecu_id,
            asset_id=asset_id,
            provenance_id=provenance_id,
            version_metadata={} if metadata is None else dict(metadata),
        )
        return ErsStoredArtifact(artifact=artifact, version=version)

    def read_version(self, version_id: UUID) -> bytes:
        version = self._repository.get_version(version_id)
        if version.availability != "available" or version.object_sha256 is None:
            raise ErsArtifactContentUnavailable(str(version_id))
        try:
            stored = self._object_store.verify(version.object_sha256)
            if stored.byte_size != version.byte_size:
                raise ObjectStoreCorruption(
                    "object size differs from artifact version metadata"
                )
            return self._object_store.read(version.object_sha256)
        except (ObjectStoreNotFound, ObjectStoreCorruption) as exc:
            raise ErsArtifactContentUnavailable(str(version_id)) from exc
