"""Immutable CRT projections; link events share the ERS transaction."""
from datetime import datetime, timezone
from sqlalchemy import select, update, func
from urllib.parse import quote
from sqlalchemy.exc import IntegrityError
from ai_bridge.domains.ers.storage.models import ErsCaseModel, ErsCaseEventModel
from ..schemas import Manifest, AIContext, FindingRequest
from .models import CRTProject, CRTSession, CRTArtifact, CRTLink, CRTFinding, utcnow


class CRTError(Exception):
    def __init__(self, detail, status=409):
        self.detail, self.status = detail, status


def snapshot(row):
    result = {column.key: getattr(row, column.key) for column in row.__table__.columns}
    for key, value in result.items():
        if isinstance(value, datetime) and value.tzinfo is None:
            result[key] = value.replace(tzinfo=timezone.utc)
    if isinstance(row, CRTSession):
        result.update(schema_id=row.manifest["schema_id"],
                      external_project_id=row.manifest["project_id"],
                      external_session_id=row.external_id,
                      projection_revision=row.manifest_version)
    return result


class CRTRepository:
    def __init__(self, database):
        self.database = database

    def import_manifest(self, manifest: Manifest):
        # Unique constraints arbitrate concurrent hash/revision allocation; retry
        # with a fresh transaction, never overwrite an imported snapshot.
        for attempt in range(3):
            try:
                with self.database.session() as db:
                    project = db.scalar(select(CRTProject).where(CRTProject.external_id == manifest.project_id))
                    if project is None:
                        project = CRTProject(external_id=manifest.project_id)
                        db.add(project)
                        db.flush()
                    identity = (CRTSession.project_id == project.id, CRTSession.external_id == manifest.session_id)
                    existing = db.scalar(select(CRTSession).where(*identity, CRTSession.manifest_hash == manifest.manifest_hash))
                    if existing:
                        return snapshot(existing)
                    revision = (db.scalar(select(func.max(CRTSession.manifest_version)).where(*identity)) or 0) + 1
                    source_uri = "crt://" + quote(manifest.project_id, safe="") + "/" + quote(manifest.session_id, safe="")
                    row = CRTSession(project_id=project.id, external_id=manifest.session_id,
                        schema_version=manifest.schema_version, manifest_version=revision,
                        manifest_hash=manifest.manifest_hash, source_uri=source_uri,
                        manifest=manifest.model_dump(mode="json"))
                    db.add(row)
                    db.flush()
                    references = [("file:" + str(i), ref) for i, ref in enumerate(manifest.files)]
                    # Keep actual selected artifact IDs; generated file keys are local
                    # indexes only. Full relative paths and roles remain in manifest.
                    artifact_ids = {a.id for a in manifest.artifacts}
                    references = [(key if key not in artifact_ids else "file:" + key, ref)
                                  for key, ref in references]
                    while any(key in artifact_ids for key, _ in references):
                        references = [("file:" + key, ref) for key, ref in references]
                    references += [(a.id, a.file) for a in manifest.artifacts]
                    for external_id, ref in references:
                        db.add(CRTArtifact(session_id=row.id, external_id=external_id,
                            source_uri=source_uri + "/" + quote(ref.relative_path, safe="/"),
                            sha256=ref.sha256, byte_size=ref.bytes,
                            media_type=ref.media_type, role=ref.role))
                    result = snapshot(row)
                return result
            except IntegrityError:
                if attempt == 2:
                    raise CRTError("concurrent_import_conflict") from None

    @staticmethod
    def _session(db, session_id):
        row = db.get(CRTSession, session_id)
        if row is None:
            raise CRTError("session_not_found", 404)
        return row

    def get(self, session_id):
        with self.database.session() as db:
            return snapshot(self._session(db, session_id))

    def sessions(self, limit=50, offset=0, project_id=None):
        with self.database.session() as db:
            query = select(CRTSession).join(CRTProject)
            if project_id is not None:
                query = query.where(CRTProject.external_id == project_id)
            return [snapshot(row) for row in db.scalars(query.order_by(CRTSession.created_at, CRTSession.id).limit(limit).offset(offset))]

    def links(self, session_id):
        with self.database.session() as db:
            self._session(db, session_id)
            return [snapshot(row) for row in db.scalars(select(CRTLink).where(CRTLink.session_id == session_id).order_by(CRTLink.created_at, CRTLink.id))]

    def link(self, session_id, case_id, role, actor_id, *, active=True):
        with self.database.session() as db:
            self._session(db, session_id)
            case = db.scalar(select(ErsCaseModel).where(ErsCaseModel.id == case_id).with_for_update())
            if case is None:
                raise CRTError("case_not_found", 404)
            row = db.scalar(select(CRTLink).where(CRTLink.session_id == session_id, CRTLink.case_id == case_id, CRTLink.role == role))
            if row is None:
                if not active:
                    raise CRTError("link_not_found", 404)
                row = CRTLink(session_id=session_id, case_id=case_id, role=role, actor_id=actor_id, active=True)
                db.add(row)
            elif row.active == active:
                return snapshot(row)
            now = utcnow()
            row.active, row.actor_id, row.updated_at = active, actor_id, now
            # CAS also protects SQLite and writers using the ERS optimistic API.
            version = case.row_version
            changed = db.execute(update(ErsCaseModel).where(ErsCaseModel.id == case_id, ErsCaseModel.row_version == version).values(row_version=version + 1, updated_at=now, updated_by=actor_id))
            if changed.rowcount != 1:
                raise CRTError("case_version_conflict")
            db.flush()
            db.add(ErsCaseEventModel(case_id=case_id, event_seq=version + 1,
                event_type="crt_session_linked" if active else "crt_session_unlinked",
                actor_id=actor_id, occurred_at=now,
                payload={"session_id": str(session_id), "link_id": str(row.id), "role": role}))
            return snapshot(row)

    def validate_context(self, session_id, context: AIContext):
        with self.database.session() as db:
            row = self._session(db, session_id)
            wire = context.model_dump(mode="json")
            manifest = row.manifest
            if (row.manifest_hash != context.manifest_sha256
                or manifest["project_id"] != context.project_id
                or manifest["session_id"] != context.session_id):
                raise CRTError("context_manifest_mismatch", 422)
            if wire["source_files"] != manifest["files"]:
                raise CRTError("context_source_mismatch", 422)
            artifacts = {a["id"]: a for a in manifest["artifacts"]}
            if {e.artifact.id for e in context.evidence} != set(artifacts):
                raise CRTError("context_artifact_selection_mismatch", 422)
            for evidence in wire["evidence"]:
                if evidence["artifact"] != artifacts[evidence["artifact"]["id"]]:
                    raise CRTError("context_artifact_mismatch", 422)
            # selected_payload is parsed JSON, not original file bytes. Its origin
            # cannot be proven from the file digest; never claim otherwise.

    def finding(self, session_id, request: FindingRequest):
        self.validate_context(session_id, request.context)
        with self.database.session() as db:
            row = CRTFinding(session_id=session_id, provider=request.provider, model=request.model,
                context_hash=request.context_hash, status=request.status, payload=request.model_dump(mode="json"))
            db.add(row)
            db.flush()
            return snapshot(row)

    def findings(self, session_id, limit=50, offset=0):
        with self.database.session() as db:
            self._session(db, session_id)
            return [snapshot(row) for row in db.scalars(select(CRTFinding).where(CRTFinding.session_id == session_id).order_by(CRTFinding.created_at, CRTFinding.id).limit(limit).offset(offset))]
