from pathlib import Path
import json

from ai_bridge.platform.operations import operations_snapshot


def test_operations_snapshot_is_bounded_and_useful(tmp_path: Path):
    current = tmp_path / "current"
    current.mkdir()
    (current / "RELEASE").write_text(
        "\n".join([
            "release_id=stage-o-test",
            "stage=O",
            "source_git_sha=" + "a" * 40,
            "migration_version=crt-projection-v1",
            "control_center_contract_version=1",
            "private_secret=must-not-leak",
        ]),
        encoding="utf-8",
    )

    status = tmp_path / "status"
    status.mkdir()
    (status / "monitor.json").write_text(json.dumps({
        "status": "PASS",
        "checked_at": "2026-09-26T06:00:00+00:00",
        "freshest_backup_age_hours": 5.5,
        "weekly_age_hours": 36.1,
        "nas_free_bytes": 123456789,
        "issues": [],
        "secret": "must-not-leak",
    }), encoding="utf-8")
    (status / "daily.json").write_text(json.dumps({
        "status": "PASS",
        "completed_at": "2026-09-26T00:30:00+00:00",
        "duration_seconds": 16.0,
        "knowledge_verify": {"status": "PASS", "evidence": "/secret/path"},
        "ers_case_store_verify": {"status": "PASS"},
        "wvc_verify": {"status": "PASS"},
        "retention": {"status": "PASS"},
        "domain_verify": {"ers": {"status": "PASS"}, "hermes": {"status": "PASS"}},
        "secrets_automation": "DEFERRED",
    }), encoding="utf-8")
    (status / "weekly.json").write_text(json.dumps({
        "status": "PASS",
        "completed_at": "2026-09-24T17:52:00+00:00",
        "restore_validation": {
            "knowledge": {"status": "PASS", "evidence": "/secret/evidence"},
            "domains": {"status": "PASS", "evidence_dir": "/secret/evidence"},
        },
        "retention": {"status": "PASS"},
    }), encoding="utf-8")

    snapshot = operations_snapshot(
        current_release=current,
        backup_status=status,
        storage_targets=(("test", "Test", tmp_path),),
    )

    assert snapshot["release"]["release_id"] == "stage-o-test"
    assert snapshot["release"]["stage"] == "O"
    assert snapshot["storage"][0]["status"] == "ready"
    assert snapshot["backup"]["monitor"]["status"] == "PASS"
    assert snapshot["backup"]["daily"]["knowledge_status"] == "PASS"
    assert snapshot["backup"]["weekly"]["restore_knowledge_status"] == "PASS"
    serialized = json.dumps(snapshot)
    assert "must-not-leak" not in serialized
    assert "/secret/" not in serialized
