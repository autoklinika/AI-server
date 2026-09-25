from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import select

from ai_bridge.storage.database import Database

from .models import (
    ErsAssetModel,
    ErsAssetRevisionModel,
    ErsCaseAssetModel,
    ErsCaseEcuModel,
    ErsCaseEventModel,
    ErsCaseModel,
    ErsDiagnosticStepModel,
    ErsDtcModel,
    ErsEcuIdentityObservationModel,
    ErsEcuModel,
    ErsEcuSoftwareObservationModel,
    ErsMeasurementModel,
    ErsSymptomModel,
)
from .repository import ErsCaseNotFound, ErsCaseVersionConflict, ErsCaseSnapshot


ASSET_KINDS = {"vehicle", "machine", "bench", "other"}
ECU_ROLES = {"original", "donor", "replacement", "target", "reference"}


@dataclass(frozen=True)
class ErsAppendResult:
    entity_id: UUID
    case: ErsCaseSnapshot
    extra_ids: dict[str, object]


def _now() -> datetime:
    return datetime.now(timezone.utc)


class ErsIntakeRepository:
    def __init__(self, database: Database) -> None:
        self._database = database

    def add_asset(
        self,
        case_id: UUID,
        *,
        expected_row_version: int,
        actor_id: str,
        asset_kind: str,
        role: str,
        manufacturer: str | None = None,
        model: str | None = None,
        vin: str | None = None,
        serial_number: str | None = None,
        production_date: date | None = None,
        engine_identity: dict | None = None,
        provenance_id: UUID | None = None,
        metadata: dict | None = None,
        request_id: str | None = None,
        correlation_id: str | None = None,
    ) -> ErsAppendResult:
        if asset_kind not in ASSET_KINDS:
            raise ValueError("invalid asset_kind")
        if not role.strip():
            raise ValueError("role is required")

        with self._database.session() as session:
            case = self._lock_case(session, case_id, expected_row_version)
            asset = ErsAssetModel(
                id=uuid4(),
                asset_kind=asset_kind,
                metadata_json={},
            )
            session.add(asset)
            session.flush()
            revision = ErsAssetRevisionModel(
                id=uuid4(),
                asset_id=asset.id,
                manufacturer=manufacturer,
                model=model,
                vin=vin,
                serial_number=serial_number,
                production_date=production_date,
                engine_identity={} if engine_identity is None else dict(engine_identity),
                provenance_id=provenance_id,
                metadata_json={} if metadata is None else dict(metadata),
            )
            link = ErsCaseAssetModel(
                id=uuid4(),
                case_id=case.id,
                asset_id=asset.id,
                role=role.strip(),
            )
            session.add_all((revision, link))
            updated = self._record_append(
                session,
                case,
                actor_id=actor_id,
                event_type="asset_added",
                payload={
                    "asset_id": str(asset.id),
                    "asset_revision_id": str(revision.id),
                    "asset_kind": asset_kind,
                    "role": role.strip(),
                },
                request_id=request_id,
                correlation_id=correlation_id,
            )
            return ErsAppendResult(
                entity_id=asset.id,
                case=updated,
                extra_ids={"revision_id": revision.id, "link_id": link.id},
            )

    def add_ecu(
        self,
        case_id: UUID,
        *,
        expected_row_version: int,
        actor_id: str,
        role: str,
        manufacturer: str | None = None,
        family: str | None = None,
        model: str | None = None,
        hardware_number: str | None = None,
        hardware_revision: str | None = None,
        assembly_part_number: str | None = None,
        serial_number: str | None = None,
        mcu_marking: str | None = None,
        software_number: str | None = None,
        calibration_number: str | None = None,
        boot_id: str | None = None,
        coding_id: str | None = None,
        dataset_id: str | None = None,
        provenance_id: UUID | None = None,
        metadata: dict | None = None,
        request_id: str | None = None,
        correlation_id: str | None = None,
    ) -> ErsAppendResult:
        if role not in ECU_ROLES:
            raise ValueError("invalid ECU role")

        with self._database.session() as session:
            case = self._lock_case(session, case_id, expected_row_version)
            ecu = ErsEcuModel(id=uuid4(), metadata_json={})
            session.add(ecu)
            session.flush()
            link = ErsCaseEcuModel(
                id=uuid4(), case_id=case.id, ecu_id=ecu.id, role=role
            )
            identity = ErsEcuIdentityObservationModel(
                id=uuid4(),
                ecu_id=ecu.id,
                case_id=case.id,
                manufacturer=manufacturer,
                family=family,
                model=model,
                hardware_number=hardware_number,
                hardware_revision=hardware_revision,
                assembly_part_number=assembly_part_number,
                serial_number=serial_number,
                mcu_marking=mcu_marking,
                provenance_id=provenance_id,
                metadata_json={} if metadata is None else dict(metadata),
            )
            software = ErsEcuSoftwareObservationModel(
                id=uuid4(),
                ecu_id=ecu.id,
                case_id=case.id,
                software_number=software_number,
                calibration_number=calibration_number,
                boot_id=boot_id,
                coding_id=coding_id,
                dataset_id=dataset_id,
                provenance_id=provenance_id,
                metadata_json={},
            )
            session.add_all((link, identity, software))
            updated = self._record_append(
                session,
                case,
                actor_id=actor_id,
                event_type="ecu_added",
                payload={"ecu_id": str(ecu.id), "role": role},
                request_id=request_id,
                correlation_id=correlation_id,
            )
            return ErsAppendResult(
                entity_id=ecu.id,
                case=updated,
                extra_ids={
                    "identity_observation_id": identity.id,
                    "software_observation_id": software.id,
                    "link_id": link.id,
                },
            )

    def add_symptom(
        self,
        case_id: UUID,
        *,
        expected_row_version: int,
        actor_id: str,
        description: str,
        operating_context: dict | None = None,
        provenance_id: UUID | None = None,
        request_id: str | None = None,
        correlation_id: str | None = None,
    ) -> ErsAppendResult:
        if not description.strip():
            raise ValueError("description is required")
        with self._database.session() as session:
            case = self._lock_case(session, case_id, expected_row_version)
            row = ErsSymptomModel(
                id=uuid4(),
                case_id=case.id,
                description=description.strip(),
                operating_context={} if operating_context is None else dict(operating_context),
                provenance_id=provenance_id,
            )
            session.add(row)
            updated = self._record_append(
                session, case, actor_id=actor_id, event_type="symptom_added",
                payload={"symptom_id": str(row.id)}, request_id=request_id,
                correlation_id=correlation_id,
            )
            return ErsAppendResult(row.id, updated, {})

    def add_dtc(
        self,
        case_id: UUID,
        *,
        expected_row_version: int,
        actor_id: str,
        protocol: str,
        ecu_id: UUID | None = None,
        code: str | None = None,
        spn: int | None = None,
        fmi: int | None = None,
        occurrence_count: int | None = None,
        status: str | None = None,
        raw_text: str | None = None,
        freeze_frame: dict | None = None,
        provenance_id: UUID | None = None,
        request_id: str | None = None,
        correlation_id: str | None = None,
    ) -> ErsAppendResult:
        if not protocol.strip():
            raise ValueError("protocol is required")
        if code is None and spn is None:
            raise ValueError("code or spn is required")
        if fmi is not None and spn is None:
            raise ValueError("fmi requires spn")

        with self._database.session() as session:
            case = self._lock_case(session, case_id, expected_row_version)
            if ecu_id is not None:
                self._require_case_ecu(session, case.id, ecu_id)
            row = ErsDtcModel(
                id=uuid4(), case_id=case.id, ecu_id=ecu_id,
                protocol=protocol.strip(), code=code, spn=spn, fmi=fmi,
                occurrence_count=occurrence_count, status=status, raw_text=raw_text,
                freeze_frame={} if freeze_frame is None else dict(freeze_frame),
                provenance_id=provenance_id,
            )
            session.add(row)
            updated = self._record_append(
                session, case, actor_id=actor_id, event_type="dtc_added",
                payload={"dtc_id": str(row.id)}, request_id=request_id,
                correlation_id=correlation_id,
            )
            return ErsAppendResult(row.id, updated, {})

    def add_measurement(
        self,
        case_id: UUID,
        *,
        expected_row_version: int,
        actor_id: str,
        measurement_type: str,
        value_numeric: float | None = None,
        value_text: str | None = None,
        value_json: dict | None = None,
        channel: str | None = None,
        unit: str | None = None,
        ecu_id: UUID | None = None,
        operating_context: dict | None = None,
        method: str | None = None,
        tool_ref: str | None = None,
        provenance_id: UUID | None = None,
        request_id: str | None = None,
        correlation_id: str | None = None,
    ) -> ErsAppendResult:
        if not measurement_type.strip():
            raise ValueError("measurement_type is required")
        values = (value_numeric is not None, value_text is not None, value_json is not None)
        if sum(values) != 1:
            raise ValueError("exactly one measurement value is required")

        with self._database.session() as session:
            case = self._lock_case(session, case_id, expected_row_version)
            if ecu_id is not None:
                self._require_case_ecu(session, case.id, ecu_id)
            row = ErsMeasurementModel(
                id=uuid4(), case_id=case.id, ecu_id=ecu_id,
                measurement_type=measurement_type.strip(), channel=channel,
                value_numeric=value_numeric, value_text=value_text, value_json=value_json,
                unit=unit,
                operating_context={} if operating_context is None else dict(operating_context),
                method=method, tool_ref=tool_ref, provenance_id=provenance_id,
            )
            session.add(row)
            updated = self._record_append(
                session, case, actor_id=actor_id, event_type="measurement_added",
                payload={"measurement_id": str(row.id)}, request_id=request_id,
                correlation_id=correlation_id,
            )
            return ErsAppendResult(row.id, updated, {})

    def add_diagnostic_step(
        self,
        case_id: UUID,
        *,
        expected_row_version: int,
        actor_id: str,
        step_type: str,
        observation: str | None = None,
        hypothesis_text: str | None = None,
        test: str | None = None,
        result: str | None = None,
        next_step: str | None = None,
        status: str | None = None,
        provenance_id: UUID | None = None,
        request_id: str | None = None,
        correlation_id: str | None = None,
    ) -> ErsAppendResult:
        if not step_type.strip():
            raise ValueError("step_type is required")

        with self._database.session() as session:
            case = self._lock_case(session, case_id, expected_row_version)
            current = session.scalar(
                select(ErsDiagnosticStepModel.step_seq)
                .where(ErsDiagnosticStepModel.case_id == case.id)
                .order_by(ErsDiagnosticStepModel.step_seq.desc())
                .limit(1)
            )
            row = ErsDiagnosticStepModel(
                id=uuid4(), case_id=case.id, step_seq=int(current or 0) + 1,
                step_type=step_type.strip(), observation=observation,
                hypothesis_text=hypothesis_text, test=test, result=result,
                next_step=next_step, status=status, provenance_id=provenance_id,
            )
            session.add(row)
            updated = self._record_append(
                session, case, actor_id=actor_id, event_type="diagnostic_step_added",
                payload={"diagnostic_step_id": str(row.id), "step_seq": row.step_seq},
                request_id=request_id, correlation_id=correlation_id,
            )
            return ErsAppendResult(row.id, updated, {"step_seq": row.step_seq})

    def get_case_detail(self, case_id: UUID) -> dict:
        with self._database.session() as session:
            case = session.get(ErsCaseModel, case_id)
            if case is None:
                raise ErsCaseNotFound(str(case_id))

            asset_links = session.scalars(
                select(ErsCaseAssetModel)
                .where(ErsCaseAssetModel.case_id == case_id)
                .order_by(ErsCaseAssetModel.created_at)
            ).all()
            asset_ids = [row.asset_id for row in asset_links]
            assets = {
                row.id: row for row in session.scalars(
                    select(ErsAssetModel).where(ErsAssetModel.id.in_(asset_ids))
                ).all()
            } if asset_ids else {}
            asset_revisions = session.scalars(
                select(ErsAssetRevisionModel)
                .where(ErsAssetRevisionModel.asset_id.in_(asset_ids))
                .order_by(ErsAssetRevisionModel.observed_at)
            ).all() if asset_ids else []

            ecu_links = session.scalars(
                select(ErsCaseEcuModel)
                .where(ErsCaseEcuModel.case_id == case_id)
                .order_by(ErsCaseEcuModel.created_at)
            ).all()
            ecu_ids = [row.ecu_id for row in ecu_links]
            identities = session.scalars(
                select(ErsEcuIdentityObservationModel)
                .where(ErsEcuIdentityObservationModel.case_id == case_id)
                .order_by(ErsEcuIdentityObservationModel.observed_at)
            ).all()
            software = session.scalars(
                select(ErsEcuSoftwareObservationModel)
                .where(ErsEcuSoftwareObservationModel.case_id == case_id)
                .order_by(ErsEcuSoftwareObservationModel.observed_at)
            ).all()

            symptoms = session.scalars(
                select(ErsSymptomModel)
                .where(ErsSymptomModel.case_id == case_id)
                .order_by(ErsSymptomModel.observed_at)
            ).all()
            dtcs = session.scalars(
                select(ErsDtcModel)
                .where(ErsDtcModel.case_id == case_id)
                .order_by(ErsDtcModel.observed_at)
            ).all()
            measurements = session.scalars(
                select(ErsMeasurementModel)
                .where(ErsMeasurementModel.case_id == case_id)
                .order_by(ErsMeasurementModel.captured_at)
            ).all()
            steps = session.scalars(
                select(ErsDiagnosticStepModel)
                .where(ErsDiagnosticStepModel.case_id == case_id)
                .order_by(ErsDiagnosticStepModel.step_seq)
            ).all()

            return {
                "case": self._case_snapshot(case),
                "assets": [{
                    "asset_id": link.asset_id,
                    "role": link.role,
                    "asset_kind": assets[link.asset_id].asset_kind,
                    "metadata": dict(assets[link.asset_id].metadata_json),
                } for link in asset_links],
                "asset_revisions": [{
                    "id": row.id, "asset_id": row.asset_id,
                    "manufacturer": row.manufacturer, "model": row.model,
                    "vin": row.vin, "serial_number": row.serial_number,
                    "production_date": row.production_date,
                    "engine_identity": dict(row.engine_identity),
                    "observed_at": row.observed_at,
                    "provenance_id": row.provenance_id,
                    "metadata": dict(row.metadata_json),
                } for row in asset_revisions],
                "ecus": [{
                    "ecu_id": link.ecu_id, "role": link.role,
                } for link in ecu_links],
                "ecu_identity_observations": [{
                    "id": row.id, "ecu_id": row.ecu_id,
                    "manufacturer": row.manufacturer, "family": row.family,
                    "model": row.model, "hardware_number": row.hardware_number,
                    "hardware_revision": row.hardware_revision,
                    "assembly_part_number": row.assembly_part_number,
                    "serial_number": row.serial_number,
                    "mcu_marking": row.mcu_marking,
                    "observed_at": row.observed_at,
                    "provenance_id": row.provenance_id,
                    "metadata": dict(row.metadata_json),
                } for row in identities],
                "ecu_software_observations": [{
                    "id": row.id, "ecu_id": row.ecu_id,
                    "software_number": row.software_number,
                    "calibration_number": row.calibration_number,
                    "boot_id": row.boot_id, "coding_id": row.coding_id,
                    "dataset_id": row.dataset_id, "observed_at": row.observed_at,
                    "provenance_id": row.provenance_id,
                    "metadata": dict(row.metadata_json),
                } for row in software],
                "symptoms": [{
                    "id": row.id, "description": row.description,
                    "operating_context": dict(row.operating_context),
                    "observed_at": row.observed_at,
                    "provenance_id": row.provenance_id,
                } for row in symptoms],
                "dtcs": [{
                    "id": row.id, "ecu_id": row.ecu_id, "protocol": row.protocol,
                    "code": row.code, "spn": row.spn, "fmi": row.fmi,
                    "occurrence_count": row.occurrence_count, "status": row.status,
                    "raw_text": row.raw_text, "freeze_frame": dict(row.freeze_frame),
                    "observed_at": row.observed_at,
                    "provenance_id": row.provenance_id,
                } for row in dtcs],
                "measurements": [{
                    "id": row.id, "ecu_id": row.ecu_id,
                    "measurement_type": row.measurement_type, "channel": row.channel,
                    "value_numeric": row.value_numeric, "value_text": row.value_text,
                    "value_json": row.value_json, "unit": row.unit,
                    "captured_at": row.captured_at,
                    "operating_context": dict(row.operating_context),
                    "method": row.method, "tool_ref": row.tool_ref,
                    "provenance_id": row.provenance_id,
                } for row in measurements],
                "diagnostic_steps": [{
                    "id": row.id, "step_seq": row.step_seq,
                    "step_type": row.step_type, "observation": row.observation,
                    "hypothesis_text": row.hypothesis_text, "test": row.test,
                    "result": row.result, "next_step": row.next_step,
                    "status": row.status, "occurred_at": row.occurred_at,
                    "provenance_id": row.provenance_id,
                } for row in steps],
            }

    @staticmethod
    def _require_case_ecu(session, case_id: UUID, ecu_id: UUID) -> None:
        link = session.scalar(
            select(ErsCaseEcuModel.id).where(
                ErsCaseEcuModel.case_id == case_id,
                ErsCaseEcuModel.ecu_id == ecu_id,
            )
        )
        if link is None:
            raise ValueError("ecu_id is not linked to this case")

    @staticmethod
    def _lock_case(session, case_id: UUID, expected_row_version: int) -> ErsCaseModel:
        if expected_row_version < 1:
            raise ValueError("expected_row_version must be >= 1")
        case = session.scalar(
            select(ErsCaseModel)
            .where(ErsCaseModel.id == case_id)
            .with_for_update()
        )
        if case is None:
            raise ErsCaseNotFound(str(case_id))
        if case.row_version != expected_row_version:
            raise ErsCaseVersionConflict(str(case_id))
        return case

    @staticmethod
    def _record_append(
        session,
        case: ErsCaseModel,
        *,
        actor_id: str,
        event_type: str,
        payload: dict,
        request_id: str | None,
        correlation_id: str | None,
    ) -> ErsCaseSnapshot:
        actor_id = actor_id.strip()
        if not actor_id:
            raise ValueError("actor_id is required")
        now = _now()
        previous_version = case.row_version
        case.row_version += 1
        case.updated_at = now
        case.updated_by = actor_id
        event = ErsCaseEventModel(
            id=uuid4(), case_id=case.id, event_seq=case.row_version,
            event_type=event_type, previous_status=case.status, new_status=case.status,
            previous_work_state=case.work_state, new_work_state=case.work_state,
            actor_id=actor_id, request_id=request_id, correlation_id=correlation_id,
            occurred_at=now, payload=dict(payload),
        )
        session.add(event)
        session.flush()
        assert case.row_version == previous_version + 1
        return ErsIntakeRepository._case_snapshot(case)

    @staticmethod
    def _case_snapshot(case: ErsCaseModel) -> ErsCaseSnapshot:
        return ErsCaseSnapshot(
            id=case.id, case_code=case.case_code, legacy_case_code=case.legacy_case_code,
            title=case.title, status=case.status, work_state=case.work_state,
            row_version=case.row_version, opened_at=case.opened_at,
            resolved_at=case.resolved_at, closed_at=case.closed_at,
            created_at=case.created_at, updated_at=case.updated_at,
            created_by=case.created_by, updated_by=case.updated_by,
            metadata=dict(case.metadata_json),
        )
