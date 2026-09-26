from __future__ import annotations

from pathlib import PurePosixPath
from uuid import UUID

from sqlalchemy import select

from ai_bridge.knowledge.storage.repository import KnowledgeDocumentSnapshot
from ai_bridge.storage.database import Database
from ai_bridge.domains.ers.storage.models import (
    ErsArtifactModel,
    ErsArtifactVersionModel,
    ErsCaseModel,
)


def _media_kind(media_type: str | None) -> str:
    value = (media_type or "").lower()
    if value == "application/pdf":
        return "pdf"
    if value.startswith("image/"):
        return "image"
    if value in {
        "text/plain",
        "text/markdown",
        "text/csv",
        "application/json",
        "application/xml",
    }:
        return "text"
    return "binary"


def _direct_role(snapshot: KnowledgeDocumentSnapshot, repository_path: str | None) -> str:
    media_type = snapshot.document.media_type.lower()
    if media_type == "application/pdf" or (repository_path and "/originals/" in repository_path):
        return "original_document"
    if media_type.startswith("image/"):
        return "original_image"
    if repository_path and repository_path.startswith("cases/"):
        return "workshop_note"
    if media_type.startswith("text/"):
        return "source_note"
    return "source_file"


def _artifact_payload(
    artifact: ErsArtifactModel,
    version: ErsArtifactVersionModel,
    *,
    relationship: str,
    same_bytes_as_document: bool = False,
) -> dict:
    return {
        "artifact_id": str(artifact.id),
        "version_id": str(version.id),
        "relationship": relationship,
        "same_bytes_as_document": same_bytes_as_document,
        "artifact_kind": artifact.artifact_kind,
        "title": artifact.title,
        "role": artifact.role,
        "filename": artifact.original_filename,
        "media_type": version.media_type,
        "media_kind": _media_kind(version.media_type),
        "availability": version.availability,
        "byte_size": version.byte_size,
        "created_at": artifact.created_at.isoformat(),
        "acquired_at": version.acquired_at.isoformat(),
    }


def resolve_source_provenance(
    database: Database,
    snapshot: KnowledgeDocumentSnapshot,
    *,
    max_related_originals: int = 24,
) -> dict:
    repository_path_value = snapshot.document.metadata.get("repository_path")
    repository_path = (
        str(repository_path_value)
        if isinstance(repository_path_value, str) and repository_path_value
        else None
    )
    filename = PurePosixPath(repository_path).name if repository_path else PurePosixPath(
        snapshot.document.uri.split("?", 1)[0]
    ).name
    if not filename:
        filename = snapshot.document.document_id

    direct = {
        "relationship": "exact_knowledge_document",
        "role": _direct_role(snapshot, repository_path),
        "filename": filename,
        "media_type": snapshot.document.media_type,
        "media_kind": _media_kind(snapshot.document.media_type),
        "byte_size": snapshot.version.byte_size,
        "content_sha256": snapshot.version.content_sha256,
        "source_type": snapshot.source.source_type,
        "source_uri": snapshot.source.uri,
        "document_uri": snapshot.document.uri,
        "repository_path": repository_path,
        "available": True,
    }

    case_payload = None
    exact_ers_artifact = None
    related_originals: list[dict] = []

    path_parts = PurePosixPath(repository_path).parts if repository_path else ()
    if len(path_parts) >= 3 and path_parts[0] == "cases":
        legacy_case_code = path_parts[1]
        relative_path = PurePosixPath(*path_parts[2:]).as_posix()

        with database.session() as session:
            case = session.scalar(
                select(ErsCaseModel).where(
                    ErsCaseModel.legacy_case_code == legacy_case_code
                )
            )
            if case is not None:
                case_payload = {
                    "case_id": str(case.id),
                    "case_code": case.case_code,
                    "legacy_case_code": case.legacy_case_code,
                    "title": case.title,
                }
                artifacts = session.scalars(
                    select(ErsArtifactModel)
                    .where(ErsArtifactModel.case_id == case.id)
                    .order_by(ErsArtifactModel.created_at, ErsArtifactModel.id)
                ).all()
                artifact_ids = [artifact.id for artifact in artifacts]
                versions = (
                    session.scalars(
                        select(ErsArtifactVersionModel)
                        .where(ErsArtifactVersionModel.artifact_id.in_(artifact_ids))
                        .order_by(
                            ErsArtifactVersionModel.artifact_id,
                            ErsArtifactVersionModel.version_no.desc(),
                        )
                    ).all()
                    if artifact_ids
                    else []
                )
                latest: dict[UUID, ErsArtifactVersionModel] = {}
                for version in versions:
                    latest.setdefault(version.artifact_id, version)

                for artifact in artifacts:
                    version = latest.get(artifact.id)
                    if version is None:
                        continue
                    metadata = dict(artifact.metadata_json)
                    source_kind = metadata.get("legacy_source_kind")
                    source_path = metadata.get("legacy_source_path")

                    if (
                        exact_ers_artifact is None
                        and source_kind == "repo_file"
                        and source_path == relative_path
                    ):
                        exact_ers_artifact = _artifact_payload(
                            artifact,
                            version,
                            relationship="exact_ers_record",
                            same_bytes_as_document=(
                                version.object_sha256 == snapshot.version.content_sha256
                            ),
                        )

                    if (
                        source_kind == "local_original"
                        and version.availability == "available"
                        and len(related_originals) < max_related_originals
                    ):
                        related_originals.append(
                            _artifact_payload(
                                artifact,
                                version,
                                relationship="same_case_original",
                            )
                        )

    return {
        "schema_version": 1,
        "document_id": snapshot.document.document_id,
        "version_id": snapshot.version.version_id,
        "direct_original": direct,
        "case": case_payload,
        "exact_ers_artifact": exact_ers_artifact,
        "related_originals": related_originals,
        "provenance_policy": {
            "exact_relationships_only": True,
            "case_related_originals_are_not_claimed_as_exact_evidence": True,
        },
    }
