from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, event, inspect, select
from sqlalchemy.exc import IntegrityError

from ai_bridge.domains.ers.storage.models import (
    ErsArtifactModel,
    ErsArtifactVersionModel,
    ErsAssetModel,
    ErsCaseAssetModel,
    ErsCaseCounterModel,
    ErsCaseEcuModel,
    ErsEcuModel,
    ErsEvidenceModel,
    ErsHypothesisEvidenceModel,
    ErsHypothesisModel,
    ErsMeasurementModel,
    ErsProvenanceRecordModel,
)
from ai_bridge.domains.ers.storage.repository import (
    ErsCaseRepository,
    ErsCaseVersionConflict,
    ErsInvalidCaseTransition,
)
from ai_bridge.storage.base import Base
from ai_bridge.storage.database import Database


ERS_TABLES = {
    "ers_case_counters",
    "ers_cases",
    "ers_case_events",
    "ers_assets",
    "ers_asset_revisions",
    "ers_case_assets",
    "ers_ecus",
    "ers_case_ecus",
    "ers_ecu_identity_observations",
    "ers_ecu_software_observations",
    "ers_symptoms",
    "ers_dtcs",
    "ers_measurements",
    "ers_diagnostic_steps",
    "ers_hypotheses",
    "ers_hypothesis_evidence",
    "ers_repair_actions",
    "ers_case_results",
    "ers_provenance_records",
    "ers_provenance_edges",
    "ers_evidence",
    "ers_artifacts",
    "ers_artifact_versions",
}


def setup_repository(tmp_path: Path) -> tuple[Database, ErsCaseRepository]:
    database = Database("sqlite+pysqlite:///" + str(tmp_path / "ers.sqlite"))

    @event.listens_for(database.engine, "connect")
    def enable_foreign_keys(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(database.engine)
    with database.session() as session:
        session.add(ErsCaseCounterModel(counter_name="case", next_value=1))
    return database, ErsCaseRepository(database)


def test_l1_migration_upgrade_seed_and_downgrade(monkeypatch, tmp_path):
    database_path = tmp_path / "migration.sqlite"
    database_url = "sqlite+pysqlite:///" + str(database_path)
    monkeypatch.setenv("AI_BRIDGE_DATABASE_URL", database_url)

    config = Config("alembic.ini")
    command.upgrade(config, "head")

    engine = create_engine(database_url)
    try:
        tables = set(inspect(engine).get_table_names())
        assert ERS_TABLES <= tables
        with engine.connect() as connection:
            row = connection.exec_driver_sql(
                "SELECT counter_name, next_value FROM ers_case_counters"
            ).one()
            assert tuple(row) == ("case", 1)
    finally:
        engine.dispose()

    command.downgrade(config, "0003_knowledge_canonical")

    engine = create_engine(database_url)
    try:
        tables = set(inspect(engine).get_table_names())
        assert ERS_TABLES.isdisjoint(tables)
    finally:
        engine.dispose()


def test_case_ids_are_monotonic_and_creation_is_audited(tmp_path):
    database, repository = setup_repository(tmp_path)

    first = repository.create_case(
        title="Scania EMS S6 clone",
        actor_id="operator",
        legacy_case_code="CASE-0002-SCANIA",
        metadata={"source": "legacy-seed"},
        request_id="req-1",
    )
    second = repository.create_case(
        title="Bench ECU",
        actor_id="operator",
        request_id="req-2",
    )

    assert first.case_code == "CASE-000001"
    assert second.case_code == "CASE-000002"
    assert first.id != second.id
    assert first.status == "draft"
    assert first.work_state == "intake"
    assert first.row_version == 1

    events = repository.list_events(first.id)
    assert len(events) == 1
    assert events[0].event_seq == 1
    assert events[0].event_type == "created"
    assert events[0].new_status == "draft"
    assert events[0].request_id == "req-1"
    database.dispose()


def test_lifecycle_is_versioned_and_closed_case_reopen_is_explicit(tmp_path):
    database, repository = setup_repository(tmp_path)
    case = repository.create_case(title="Lifecycle", actor_id="operator")

    case = repository.transition_status(
        case.id, to_status="open", expected_row_version=1, actor_id="operator"
    )
    assert case.row_version == 2
    assert case.opened_at is not None

    case = repository.transition_status(
        case.id, to_status="resolved", expected_row_version=2, actor_id="operator"
    )
    assert case.row_version == 3
    assert case.resolved_at is not None

    case = repository.transition_status(
        case.id, to_status="closed", expected_row_version=3, actor_id="operator"
    )
    assert case.row_version == 4
    assert case.closed_at is not None

    case = repository.transition_status(
        case.id, to_status="open", expected_row_version=4, actor_id="operator"
    )
    assert case.row_version == 5
    assert case.resolved_at is None
    assert case.closed_at is None

    events = repository.list_events(case.id)
    assert [event.event_seq for event in events] == [1, 2, 3, 4, 5]
    assert events[-1].event_type == "reopened"
    assert events[-1].previous_status == "closed"
    assert events[-1].new_status == "open"
    database.dispose()


def test_invalid_transition_and_stale_write_fail_closed(tmp_path):
    database, repository = setup_repository(tmp_path)
    case = repository.create_case(title="Concurrency", actor_id="operator")

    with pytest.raises(ErsInvalidCaseTransition):
        repository.transition_status(
            case.id,
            to_status="closed",
            expected_row_version=1,
            actor_id="operator",
        )

    opened = repository.transition_status(
        case.id, to_status="open", expected_row_version=1, actor_id="operator"
    )
    assert opened.row_version == 2

    with pytest.raises(ErsCaseVersionConflict):
        repository.update_case(
            case.id,
            expected_row_version=1,
            actor_id="stale-client",
            work_state="diagnosing",
        )

    current = repository.get_case(case.id)
    assert current.row_version == 2
    assert current.work_state == "intake"
    assert len(repository.list_events(case.id)) == 2
    database.dispose()


def test_case_update_creates_event_and_replaces_mutable_header(tmp_path):
    database, repository = setup_repository(tmp_path)
    case = repository.create_case(
        title="Initial title",
        actor_id="operator",
        metadata={"phase": 1},
    )

    updated = repository.update_case(
        case.id,
        expected_row_version=1,
        actor_id="operator",
        title="Updated title",
        work_state="diagnosing",
        metadata={"phase": 2},
        correlation_id="corr-1",
    )

    assert updated.row_version == 2
    assert updated.title == "Updated title"
    assert updated.work_state == "diagnosing"
    assert updated.metadata == {"phase": 2}

    event_row = repository.list_events(case.id)[-1]
    assert event_row.event_type == "updated"
    assert event_row.event_seq == 2
    assert event_row.previous_work_state == "intake"
    assert event_row.new_work_state == "diagnosing"
    assert event_row.correlation_id == "corr-1"
    database.dispose()


def test_core_evidence_graph_persists_relations(tmp_path):
    database, repository = setup_repository(tmp_path)
    case = repository.create_case(title="Evidence graph", actor_id="operator")

    provenance_id = uuid4()
    asset_id = uuid4()
    ecu_id = uuid4()
    measurement_id = uuid4()
    artifact_id = uuid4()
    artifact_version_id = uuid4()
    hypothesis_id = uuid4()
    evidence_id = uuid4()

    with database.session() as session:
        session.add(ErsProvenanceRecordModel(
            id=provenance_id,
            origin_type="workshop_upload",
            actor_id="operator",
            acquisition_method="upload",
            metadata_json={},
        ))
        session.add(ErsAssetModel(id=asset_id, asset_kind="vehicle", metadata_json={}))
        session.add(ErsEcuModel(id=ecu_id, metadata_json={}))
        session.flush()
        session.add(ErsCaseAssetModel(
            id=uuid4(), case_id=case.id, asset_id=asset_id, role="subject"
        ))
        session.add(ErsCaseEcuModel(
            id=uuid4(), case_id=case.id, ecu_id=ecu_id, role="original"
        ))
        session.add(ErsMeasurementModel(
            id=measurement_id,
            case_id=case.id,
            ecu_id=ecu_id,
            measurement_type="supply_voltage",
            channel="KL30",
            value_numeric=24.3,
            unit="V",
            operating_context={"ignition": "on"},
            provenance_id=provenance_id,
        ))
        session.add(ErsArtifactModel(
            id=artifact_id,
            case_id=case.id,
            ecu_id=ecu_id,
            asset_id=asset_id,
            artifact_kind="binary",
            title="ORI flash",
            original_filename="ori.bin",
            created_by="operator",
            metadata_json={},
        ))
        session.flush()
        session.add(ErsArtifactVersionModel(
            id=artifact_version_id,
            artifact_id=artifact_id,
            version_no=1,
            object_sha256="a" * 64,
            byte_size=458752,
            media_type="application/octet-stream",
            availability="available",
            provenance_id=provenance_id,
            metadata_json={},
        ))
        session.add(ErsHypothesisModel(
            id=hypothesis_id,
            case_id=case.id,
            statement="Power rail is unstable",
            status="proposed",
            confidence=0.4,
            created_by="operator",
            provenance_id=provenance_id,
        ))
        session.flush()
        session.add(ErsEvidenceModel(
            id=evidence_id,
            case_id=case.id,
            authority="measured_data",
            evidence_type="measurement",
            statement="KL30 measured 24.3 V",
            artifact_version_id=artifact_version_id,
            measurement_id=measurement_id,
            locator={"channel": "KL30"},
            provenance_id=provenance_id,
        ))
        session.flush()
        session.add(ErsHypothesisEvidenceModel(
            id=uuid4(),
            hypothesis_id=hypothesis_id,
            evidence_id=evidence_id,
            polarity="context",
        ))

    with database.session() as session:
        evidence = session.get(ErsEvidenceModel, evidence_id)
        link = session.scalar(select(ErsHypothesisEvidenceModel))
        assert evidence.artifact_version_id == artifact_version_id
        assert evidence.measurement_id == measurement_id
        assert evidence.locator == {"channel": "KL30"}
        assert link.hypothesis_id == hypothesis_id
        assert link.evidence_id == evidence_id
    database.dispose()


def test_available_artifact_requires_hash(tmp_path):
    database, repository = setup_repository(tmp_path)
    case = repository.create_case(title="Artifact constraint", actor_id="operator")

    with pytest.raises(IntegrityError):
        with database.session() as session:
            artifact = ErsArtifactModel(
                id=uuid4(),
                case_id=case.id,
                artifact_kind="binary",
                created_by="operator",
                metadata_json={},
            )
            session.add(artifact)
            session.flush()
            session.add(ErsArtifactVersionModel(
                id=uuid4(),
                artifact_id=artifact.id,
                version_no=1,
                object_sha256=None,
                byte_size=1,
                availability="available",
                metadata_json={},
            ))
    database.dispose()
