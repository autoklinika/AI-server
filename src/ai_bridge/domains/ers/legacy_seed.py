from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import select

from ai_bridge.storage.database import Database
from ai_bridge.storage.object_store import ObjectStore

from .legacy_seed_schemas import LegacyCaseSeed, SeedArtifact
from .storage.models import (
    ErsArtifactModel,
    ErsArtifactVersionModel,
    ErsAssetModel,
    ErsAssetRevisionModel,
    ErsCaseAssetModel,
    ErsCaseEcuModel,
    ErsCaseEventModel,
    ErsCaseModel,
    ErsCaseResultModel,
    ErsDiagnosticStepModel,
    ErsDtcModel,
    ErsEcuIdentityObservationModel,
    ErsEcuModel,
    ErsEcuSoftwareObservationModel,
    ErsProvenanceRecordModel,
    ErsRepairActionModel,
    ErsSymptomModel,
)
from .storage.repository import CASE_TRANSITIONS, ErsCaseRepository


ACTOR = "migration:stage-l1.4"
TOOL_VERSION = "legacy-seed-v1"


class ErsLegacySeedConflict(RuntimeError):
    pass


class ErsLegacySeedInvalid(ValueError):
    pass


@dataclass(frozen=True)
class SeedArtifactPlan:
    artifact: SeedArtifact
    path: Path
    sha256: str
    byte_size: int


@dataclass(frozen=True)
class LegacySeedPlan:
    seed_path: Path
    case_dir: Path
    source_revision: str
    fingerprint: str
    seed: LegacyCaseSeed
    artifacts: tuple[SeedArtifactPlan, ...]


@dataclass(frozen=True)
class LegacySeedImportResult:
    case_id: UUID
    case_code: str
    legacy_case_code: str
    fingerprint: str
    artifacts: int
    object_hashes: tuple[str, ...]
    state: str


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()

class LegacySeedImporter:
    def __init__(
        self,
        *,
        database: Database | None = None,
        object_store: ObjectStore | None = None,
    ) -> None:
        self._database = database
        self._object_store = object_store

    def plan(
        self,
        seed_path: Path,
        *,
        source_revision: str,
    ) -> LegacySeedPlan:
        seed_path = seed_path.resolve()
        if not seed_path.is_file() or seed_path.is_symlink():
            raise ErsLegacySeedInvalid(f"seed file unavailable: {seed_path}")
        if seed_path.name != "case.seed.json":
            raise ErsLegacySeedInvalid("seed filename must be case.seed.json")
        if not source_revision.strip():
            raise ErsLegacySeedInvalid("source_revision is required")

        try:
            raw = seed_path.read_bytes()
            seed = LegacyCaseSeed.model_validate_json(raw)
        except Exception as exc:
            raise ErsLegacySeedInvalid(f"invalid seed: {seed_path}") from exc

        case_dir = seed_path.parent.resolve()
        artifact_plans: list[SeedArtifactPlan] = []
        seen_paths: set[str] = set()

        for artifact in seed.artifacts:
            if artifact.path in seen_paths:
                raise ErsLegacySeedInvalid(
                    f"duplicate artifact path: {artifact.path}"
                )
            seen_paths.add(artifact.path)
            path = self._resolve_case_path(case_dir, artifact.path)
            if not path.is_file() or path.is_symlink():
                raise ErsLegacySeedInvalid(
                    f"artifact file unavailable: {artifact.path}"
                )
            size = path.stat().st_size
            digest = _file_sha256(path)
            if artifact.source_kind == "local_original":
                if size != artifact.byte_size:
                    raise ErsLegacySeedInvalid(
                        f"artifact size mismatch: {artifact.path}"
                    )
                if digest != artifact.sha256:
                    raise ErsLegacySeedInvalid(
                        f"artifact hash mismatch: {artifact.path}"
                    )
            artifact_plans.append(
                SeedArtifactPlan(
                    artifact=artifact,
                    path=path,
                    sha256=digest,
                    byte_size=size,
                )
            )

        fingerprint = self._fingerprint(seed, artifact_plans)
        return LegacySeedPlan(
            seed_path=seed_path,
            case_dir=case_dir,
            source_revision=source_revision.strip(),
            fingerprint=fingerprint,
            seed=seed,
            artifacts=tuple(artifact_plans),
        )

    def apply(self, plan: LegacySeedPlan) -> LegacySeedImportResult:
        if self._database is None or self._object_store is None:
            raise RuntimeError("apply requires explicit database and object_store")

        existing = self._existing_by_legacy_code(plan.seed.legacy_case_code)
        if existing is not None:
            return self._reuse_or_conflict(existing, plan)

        stored_by_path: dict[str, tuple[str, int]] = {}
        for item in plan.artifacts:
            stored = self._object_store.put(item.path.read_bytes())
            if stored.sha256 != item.sha256 or stored.byte_size != item.byte_size:
                raise ErsLegacySeedInvalid(
                    f"ObjectStore verification mismatch: {item.artifact.path}"
                )
            stored_by_path[item.artifact.path] = (
                stored.sha256,
                stored.byte_size,
            )

        return self._apply_database(plan, stored_by_path)

    def _existing_by_legacy_code(self, legacy_case_code: str) -> ErsCaseModel | None:
        assert self._database is not None
        with self._database.session() as session:
            row = session.scalar(
                select(ErsCaseModel).where(
                    ErsCaseModel.legacy_case_code == legacy_case_code
                )
            )
            if row is None:
                return None
            session.expunge(row)
            return row

    @staticmethod
    def _reuse_or_conflict(
        row: ErsCaseModel,
        plan: LegacySeedPlan,
    ) -> LegacySeedImportResult:
        metadata = dict(row.metadata_json)
        migration = metadata.get("legacy_seed")
        if not isinstance(migration, dict):
            raise ErsLegacySeedConflict(
                "legacy case already exists without legacy_seed metadata"
            )
        if migration.get("state") != "complete":
            raise ErsLegacySeedConflict("legacy seed import is not complete")
        if migration.get("fingerprint") != plan.fingerprint:
            raise ErsLegacySeedConflict(
                "legacy case exists with a different seed fingerprint"
            )
        return LegacySeedImportResult(
            case_id=row.id,
            case_code=row.case_code,
            legacy_case_code=plan.seed.legacy_case_code,
            fingerprint=plan.fingerprint,
            artifacts=int(migration.get("artifact_count", 0)),
            object_hashes=tuple(migration.get("object_hashes", ())),
            state="reused",
        )

    def _apply_database(
        self,
        plan: LegacySeedPlan,
        stored_by_path: dict[str, tuple[str, int]],
    ) -> LegacySeedImportResult:
        assert self._database is not None
        now = _now()
        seed = plan.seed
        object_hashes = tuple(
            stored_by_path[item.artifact.path][0] for item in plan.artifacts
        )

        with self._database.session() as session:
            concurrent = session.scalar(
                select(ErsCaseModel).where(
                    ErsCaseModel.legacy_case_code == seed.legacy_case_code
                )
            )
            if concurrent is not None:
                return self._reuse_or_conflict(concurrent, plan)

            number = ErsCaseRepository._allocate_case_number(session)
            metadata = dict(seed.case_metadata)
            metadata["legacy_seed"] = {
                "schema_version": seed.schema_version,
                "state": "complete",
                "fingerprint": plan.fingerprint,
                "source_revision": plan.source_revision,
                "seed_path": plan.seed_path.name,
                "artifact_count": len(plan.artifacts),
                "object_hashes": list(object_hashes),
                "tool_version": TOOL_VERSION,
            }
            case = ErsCaseModel(
                id=uuid4(),
                case_code=f"CASE-{number:06d}",
                legacy_case_code=seed.legacy_case_code,
                title=seed.title,
                status="draft",
                work_state="intake",
                row_version=1,
                created_at=now,
                updated_at=now,
                created_by=ACTOR,
                updated_by=ACTOR,
                metadata_json=metadata,
            )
            session.add(case)
            session.flush()
            self._event(
                session,
                case,
                event_type="created",
                previous_status=None,
                new_status="draft",
                previous_work_state=None,
                new_work_state="intake",
                payload={"migration": TOOL_VERSION},
                occurred_at=now,
            )

            provenance = ErsProvenanceRecordModel(
                id=uuid4(),
                origin_type="legacy_seed",
                origin_uri=plan.seed_path.resolve().as_uri(),
                origin_ref=plan.source_revision,
                actor_id=ACTOR,
                acquisition_method="deterministic_seed_import",
                tool="ers-legacy-seed",
                tool_version=TOOL_VERSION,
                acquired_at=now,
                metadata_json={
                    "fingerprint": plan.fingerprint,
                    "legacy_case_code": seed.legacy_case_code,
                },
            )
            session.add(provenance)
            session.flush()

            asset_id = self._add_asset(session, case, seed, provenance.id)
            ecu_ids = self._add_ecus(session, case, seed, provenance.id)
            self._add_symptoms(session, case, seed, provenance.id)
            self._add_dtcs(session, case, seed, provenance.id, ecu_ids)
            self._add_steps(session, case, seed, provenance.id)
            self._add_repairs(session, case, seed, provenance.id)
            self._add_results(session, case, seed, provenance.id)
            self._add_artifacts(
                session,
                case,
                plan,
                provenance.id,
                ecu_ids,
                asset_id,
                stored_by_path,
            )
            self._set_work_state(session, case, seed.final_work_state)
            self._drive_lifecycle(session, case, seed.final_status)
            session.flush()

            return LegacySeedImportResult(
                case_id=case.id,
                case_code=case.case_code,
                legacy_case_code=seed.legacy_case_code,
                fingerprint=plan.fingerprint,
                artifacts=len(plan.artifacts),
                object_hashes=object_hashes,
                state="created",
            )

    @staticmethod
    def _add_asset(session, case, seed, provenance_id) -> UUID | None:
        if seed.asset is None:
            return None
        spec = seed.asset
        asset = ErsAssetModel(
            id=uuid4(),
            asset_kind=spec.asset_kind,
            metadata_json={},
        )
        session.add(asset)
        session.flush()
        revision = ErsAssetRevisionModel(
            id=uuid4(),
            asset_id=asset.id,
            manufacturer=spec.manufacturer,
            model=spec.model,
            serial_number=spec.serial_number,
            engine_identity=dict(spec.engine_identity),
            provenance_id=provenance_id,
            metadata_json=dict(spec.metadata),
        )
        link = ErsCaseAssetModel(
            id=uuid4(),
            case_id=case.id,
            asset_id=asset.id,
            role=spec.role,
        )
        session.add_all((revision, link))
        LegacySeedImporter._append_event(
            session,
            case,
            "asset_added",
            {"asset_id": str(asset.id), "role": spec.role},
        )
        return asset.id

    @staticmethod
    def _add_ecus(session, case, seed, provenance_id) -> dict[str, UUID]:
        result: dict[str, UUID] = {}
        for spec in seed.ecus:
            ecu = ErsEcuModel(id=uuid4(), metadata_json={})
            session.add(ecu)
            session.flush()
            session.add(
                ErsCaseEcuModel(
                    id=uuid4(),
                    case_id=case.id,
                    ecu_id=ecu.id,
                    role=spec.role,
                )
            )
            session.add(
                ErsEcuIdentityObservationModel(
                    id=uuid4(),
                    ecu_id=ecu.id,
                    case_id=case.id,
                    manufacturer=spec.manufacturer,
                    family=spec.family,
                    model=spec.model,
                    hardware_number=spec.hardware_number,
                    hardware_revision=spec.hardware_revision,
                    assembly_part_number=spec.assembly_part_number,
                    serial_number=spec.serial_number,
                    mcu_marking=spec.mcu_marking,
                    provenance_id=provenance_id,
                    metadata_json=dict(spec.metadata),
                )
            )
            session.add(
                ErsEcuSoftwareObservationModel(
                    id=uuid4(),
                    ecu_id=ecu.id,
                    case_id=case.id,
                    software_number=spec.software_number,
                    calibration_number=spec.calibration_number,
                    boot_id=spec.boot_id,
                    coding_id=spec.coding_id,
                    dataset_id=spec.dataset_id,
                    provenance_id=provenance_id,
                    metadata_json={},
                )
            )
            result[spec.role] = ecu.id
            LegacySeedImporter._append_event(
                session,
                case,
                "ecu_added",
                {"ecu_id": str(ecu.id), "role": spec.role},
            )
        return result

    @staticmethod
    def _add_symptoms(session, case, seed, provenance_id) -> None:
        for spec in seed.symptoms:
            row = ErsSymptomModel(
                id=uuid4(),
                case_id=case.id,
                description=spec.description,
                operating_context=dict(spec.operating_context),
                provenance_id=provenance_id,
            )
            session.add(row)
            LegacySeedImporter._append_event(
                session, case, "symptom_added", {"symptom_id": str(row.id)}
            )

    @staticmethod
    def _add_dtcs(session, case, seed, provenance_id, ecu_ids) -> None:
        for spec in seed.dtcs:
            row = ErsDtcModel(
                id=uuid4(),
                case_id=case.id,
                ecu_id=None if spec.ecu_role is None else ecu_ids[spec.ecu_role],
                protocol=spec.protocol,
                code=spec.code,
                spn=spec.spn,
                fmi=spec.fmi,
                occurrence_count=spec.occurrence_count,
                status=spec.status,
                raw_text=spec.raw_text,
                freeze_frame=dict(spec.freeze_frame),
                provenance_id=provenance_id,
            )
            session.add(row)
            LegacySeedImporter._append_event(
                session, case, "dtc_added", {"dtc_id": str(row.id)}
            )

    @staticmethod
    def _add_steps(session, case, seed, provenance_id) -> None:
        for ordinal, spec in enumerate(seed.diagnostic_steps, start=1):
            row = ErsDiagnosticStepModel(
                id=uuid4(),
                case_id=case.id,
                step_seq=ordinal,
                step_type=spec.step_type,
                observation=spec.observation,
                hypothesis_text=spec.hypothesis_text,
                test=spec.test,
                result=spec.result,
                next_step=spec.next_step,
                status=spec.status,
                provenance_id=provenance_id,
            )
            session.add(row)
            LegacySeedImporter._append_event(
                session,
                case,
                "diagnostic_step_added",
                {"diagnostic_step_id": str(row.id), "step_seq": ordinal},
            )

    @staticmethod
    def _add_repairs(session, case, seed, provenance_id) -> None:
        for spec in seed.repair_actions:
            row = ErsRepairActionModel(
                id=uuid4(),
                case_id=case.id,
                action=spec.action,
                status=spec.status,
                result_text=spec.result_text,
                actor_id=ACTOR,
                provenance_id=provenance_id,
            )
            session.add(row)
            LegacySeedImporter._append_event(
                session,
                case,
                "repair_action_added",
                {"repair_action_id": str(row.id), "status": spec.status},
            )

    @staticmethod
    def _add_results(session, case, seed, provenance_id) -> None:
        previous: UUID | None = None
        for spec in seed.results:
            row = ErsCaseResultModel(
                id=uuid4(),
                case_id=case.id,
                outcome=spec.outcome,
                root_cause_statement=spec.root_cause_statement,
                verification=spec.verification,
                confirmation_status=spec.confirmation_status,
                supersedes_result_id=previous,
                actor_id=ACTOR,
                provenance_id=provenance_id,
            )
            session.add(row)
            previous = row.id
            LegacySeedImporter._append_event(
                session,
                case,
                "result_added",
                {"result_id": str(row.id), "outcome": spec.outcome},
            )

    @staticmethod
    def _add_artifacts(
        session,
        case,
        plan,
        provenance_id,
        ecu_ids,
        asset_id,
        stored_by_path,
    ) -> None:
        for item in plan.artifacts:
            spec = item.artifact
            digest, size = stored_by_path[spec.path]
            artifact = ErsArtifactModel(
                id=uuid4(),
                case_id=case.id,
                ecu_id=None if spec.ecu_role is None else ecu_ids[spec.ecu_role],
                asset_id=asset_id,
                artifact_kind=spec.artifact_kind,
                title=spec.role,
                role=spec.role,
                original_filename=item.path.name,
                created_by=ACTOR,
                metadata_json={
                    "legacy_source_kind": spec.source_kind,
                    "legacy_source_path": spec.path,
                },
            )
            session.add(artifact)
            session.flush()
            version = ErsArtifactVersionModel(
                id=uuid4(),
                artifact_id=artifact.id,
                version_no=1,
                object_sha256=digest,
                byte_size=size,
                media_type=spec.media_type,
                availability="available",
                provenance_id=provenance_id,
                metadata_json={"legacy_seed_fingerprint": plan.fingerprint},
            )
            session.add(version)
            LegacySeedImporter._append_event(
                session,
                case,
                "artifact_added",
                {
                    "artifact_id": str(artifact.id),
                    "artifact_version_id": str(version.id),
                    "role": spec.role,
                },
            )

    @staticmethod
    def _set_work_state(session, case, target: str | None) -> None:
        if target is None or target == case.work_state:
            return
        previous = case.work_state
        case.work_state = target
        LegacySeedImporter._append_event(
            session,
            case,
            "updated",
            {
                "migration_work_state": True,
                "from": previous,
                "to": target,
            },
            previous_work_state=previous,
        )

    @staticmethod
    def _drive_lifecycle(session, case, target: str) -> None:
        if target == case.status:
            return
        routes = {
            "open": ["open"],
            "resolved": ["open", "resolved"],
            "closed": ["open", "resolved", "closed"],
            "cancelled": ["cancelled"],
            "draft": [],
        }
        for status in routes[target]:
            if status == case.status:
                continue
            if status not in CASE_TRANSITIONS[case.status]:
                raise ErsLegacySeedInvalid(
                    f"cannot drive lifecycle {case.status} -> {status}"
                )
            previous = case.status
            now = _now()
            case.status = status
            if status == "open":
                case.opened_at = case.opened_at or now
            elif status == "resolved":
                case.resolved_at = now
            elif status == "closed":
                case.closed_at = now
            LegacySeedImporter._append_event(
                session,
                case,
                "status_changed",
                {"migration_lifecycle": True},
                previous_status=previous,
                new_status=status,
                occurred_at=now,
            )

    @staticmethod
    def _append_event(
        session,
        case,
        event_type: str,
        payload: dict,
        *,
        previous_status: str | None = None,
        new_status: str | None = None,
        previous_work_state: str | None = None,
        new_work_state: str | None = None,
        occurred_at: datetime | None = None,
    ) -> None:
        before_status = case.status if previous_status is None else previous_status
        after_status = case.status if new_status is None else new_status
        before_work = (
            case.work_state
            if previous_work_state is None
            else previous_work_state
        )
        after_work = case.work_state if new_work_state is None else new_work_state
        case.row_version += 1
        case.updated_at = occurred_at or _now()
        case.updated_by = ACTOR
        session.add(
            ErsCaseEventModel(
                id=uuid4(),
                case_id=case.id,
                event_seq=case.row_version,
                event_type=event_type,
                previous_status=before_status,
                new_status=after_status,
                previous_work_state=before_work,
                new_work_state=after_work,
                actor_id=ACTOR,
                occurred_at=case.updated_at,
                payload=dict(payload),
            )
        )

    @staticmethod
    def _event(
        session,
        case,
        *,
        event_type,
        previous_status,
        new_status,
        previous_work_state,
        new_work_state,
        payload,
        occurred_at,
    ) -> None:
        session.add(
            ErsCaseEventModel(
                id=uuid4(),
                case_id=case.id,
                event_seq=case.row_version,
                event_type=event_type,
                previous_status=previous_status,
                new_status=new_status,
                previous_work_state=previous_work_state,
                new_work_state=new_work_state,
                actor_id=ACTOR,
                occurred_at=occurred_at,
                payload=dict(payload),
            )
        )

    @staticmethod
    def _resolve_case_path(case_dir: Path, raw_path: str) -> Path:
        candidate = (case_dir / raw_path).resolve()
        try:
            candidate.relative_to(case_dir)
        except ValueError as exc:
            raise ErsLegacySeedInvalid(
                f"artifact path escapes case directory: {raw_path}"
            ) from exc
        return candidate

    @staticmethod
    def _fingerprint(
        seed: LegacyCaseSeed,
        artifacts: list[SeedArtifactPlan],
    ) -> str:
        payload = {
            "seed": seed.model_dump(mode="json", exclude_none=False),
            "artifacts": [
                {
                    "path": item.artifact.path,
                    "sha256": item.sha256,
                    "byte_size": item.byte_size,
                }
                for item in artifacts
            ],
        }
        raw = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        return sha256(raw).hexdigest()
