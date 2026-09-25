from __future__ import annotations

import json
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import func, select

from ai_bridge.domains.ers.legacy_seed import (
    ErsLegacySeedConflict,
    ErsLegacySeedInvalid,
    LegacySeedImporter,
)
from ai_bridge.domains.ers.storage.models import (
    ErsArtifactModel,
    ErsArtifactVersionModel,
    ErsCaseEventModel,
    ErsCaseModel,
    ErsCaseResultModel,
    ErsRepairActionModel,
)
from ai_bridge.storage.database import Database
from ai_bridge.storage.object_store import FileObjectStore


def write_seed(root: Path) -> Path:
    case = root / "cases" / "CASE-LEGACY"
    originals = case / "local-originals"
    originals.mkdir(parents=True)
    (case / "README.md").write_text("# Case\n\nVerified legacy case.\n")
    raw = b"legacy-binary-content"
    (originals / "ori.bin").write_bytes(raw)

    import hashlib
    seed = {
        "schema_version": 1,
        "legacy_case_code": "CASE-LEGACY",
        "title": "Legacy case",
        "final_status": "closed",
        "final_work_state": "none",
        "case_metadata": {"case_date": "2026-09-01"},
        "asset": {
            "asset_kind": "bench",
            "role": "subject",
            "manufacturer": "Fixture",
            "model": "Bench",
            "engine_identity": {},
            "metadata": {},
        },
        "ecus": [{
            "role": "original",
            "manufacturer": "Fixture",
            "family": "ECU",
            "hardware_number": "HW1",
            "software_number": "SW1",
            "metadata": {},
        }],
        "symptoms": [{
            "description": "No communication",
            "operating_context": {"bench": True},
        }],
        "dtcs": [{
            "protocol": "UDS",
            "ecu_role": "original",
            "code": "U0001",
            "status": "historical",
            "freeze_frame": {},
        }],

        "diagnostic_steps": [{
            "step_type": "verification",
            "observation": "Power present",
            "result": "Communication restored",
        }],
        "repair_actions": [{
            "action": "Repair connector",
            "status": "performed",
            "result_text": "Communication restored",
        }],
        "results": [{
            "outcome": "repaired",
            "root_cause_statement": "Connector fault",
            "verification": "Bench communication OK",
            "confirmation_status": "workshop_confirmed",
        }],
        "artifacts": [
            {
                "artifact_kind": "text",
                "role": "case_summary",
                "source_kind": "repo_file",
                "path": "README.md",
                "media_type": "text/markdown",
            },
            {
                "artifact_kind": "binary",
                "role": "original_flash",
                "source_kind": "local_original",
                "path": "local-originals/ori.bin",
                "media_type": "application/octet-stream",
                "ecu_role": "original",
                "byte_size": len(raw),
                "sha256": hashlib.sha256(raw).hexdigest(),
            },
        ],
    }
    path = case / "case.seed.json"
    path.write_text(json.dumps(seed, indent=2) + "\n")
    return path


def setup_database(tmp_path: Path, monkeypatch) -> Database:
    path = tmp_path / "legacy.sqlite"
    url = "sqlite+pysqlite:///" + str(path)
    monkeypatch.setenv("AI_BRIDGE_DATABASE_URL", url)
    config = Config("alembic.ini")
    command.upgrade(config, "head")
    return Database(url)


def count_rows(database: Database) -> dict[str, int]:
    with database.session() as session:
        return {
            "cases": session.scalar(select(func.count()).select_from(ErsCaseModel)),
            "events": session.scalar(select(func.count()).select_from(ErsCaseEventModel)),
            "artifacts": session.scalar(select(func.count()).select_from(ErsArtifactModel)),
            "versions": session.scalar(select(func.count()).select_from(ErsArtifactVersionModel)),
            "repairs": session.scalar(select(func.count()).select_from(ErsRepairActionModel)),
            "results": session.scalar(select(func.count()).select_from(ErsCaseResultModel)),
        }

def test_plan_is_read_only_and_fingerprint_tracks_repo_content(tmp_path):
    seed = write_seed(tmp_path)
    importer = LegacySeedImporter()

    first = importer.plan(seed, source_revision="rev-a")
    assert first.seed.legacy_case_code == "CASE-LEGACY"
    assert len(first.artifacts) == 2
    assert not (tmp_path / "objects").exists()

    (seed.parent / "README.md").write_text("# Case\n\nChanged content.\n")
    second = importer.plan(seed, source_revision="rev-b")
    assert second.fingerprint != first.fingerprint


def test_plan_rejects_local_original_hash_mismatch(tmp_path):
    seed = write_seed(tmp_path)
    data = json.loads(seed.read_text())
    data["artifacts"][1]["sha256"] = "0" * 64
    seed.write_text(json.dumps(data))

    with pytest.raises(ErsLegacySeedInvalid, match="hash mismatch"):
        LegacySeedImporter().plan(seed, source_revision="rev")


def test_plan_rejects_path_escape(tmp_path):
    seed = write_seed(tmp_path)
    outside = tmp_path / "outside.txt"
    outside.write_text("secret")
    data = json.loads(seed.read_text())
    data["artifacts"][0]["path"] = "../../outside.txt"
    seed.write_text(json.dumps(data))

    with pytest.raises(ErsLegacySeedInvalid, match="escapes case directory"):
        LegacySeedImporter().plan(seed, source_revision="rev")


def test_apply_is_complete_and_idempotent(tmp_path, monkeypatch):
    seed = write_seed(tmp_path)
    database = setup_database(tmp_path, monkeypatch)
    store = FileObjectStore(tmp_path / "objects")
    importer = LegacySeedImporter(database=database, object_store=store)
    plan = importer.plan(seed, source_revision="rev-a")

    first = importer.apply(plan)
    assert first.state == "created"
    assert first.case_code == "CASE-000001"
    assert first.artifacts == 2
    assert len(first.object_hashes) == 2

    with database.session() as session:
        case = session.get(ErsCaseModel, first.case_id)
        assert case.status == "closed"
        assert case.work_state == "none"
        assert case.metadata_json["legacy_seed"]["fingerprint"] == plan.fingerprint
        assert case.metadata_json["legacy_seed"]["state"] == "complete"
        events = session.scalars(
            select(ErsCaseEventModel)
            .where(ErsCaseEventModel.case_id == first.case_id)
            .order_by(ErsCaseEventModel.event_seq)
        ).all()
        assert [row.event_seq for row in events] == list(range(1, len(events) + 1))
        assert events[-3].new_status == "open"
        assert events[-2].new_status == "resolved"
        assert events[-1].new_status == "closed"

    baseline = count_rows(database)
    second = importer.apply(plan)
    assert second.state == "reused"
    assert second.case_id == first.case_id
    assert count_rows(database) == baseline
    database.dispose()


def test_changed_seed_conflicts_with_existing_import(tmp_path, monkeypatch):
    seed = write_seed(tmp_path)
    database = setup_database(tmp_path, monkeypatch)
    importer = LegacySeedImporter(
        database=database,
        object_store=FileObjectStore(tmp_path / "objects"),
    )
    first = importer.plan(seed, source_revision="rev-a")
    importer.apply(first)

    data = json.loads(seed.read_text())
    data["title"] = "Changed legacy case"
    seed.write_text(json.dumps(data))
    changed = importer.plan(seed, source_revision="rev-b")

    with pytest.raises(ErsLegacySeedConflict, match="different seed fingerprint"):
        importer.apply(changed)
    assert count_rows(database)["cases"] == 1
    database.dispose()

def test_apply_requires_explicit_dependencies(tmp_path):
    seed = write_seed(tmp_path)
    plan = LegacySeedImporter().plan(seed, source_revision="rev")
    with pytest.raises(RuntimeError, match="explicit database"):
        LegacySeedImporter().apply(plan)
