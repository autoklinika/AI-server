"""Release gate synthetic tests: automated conditions never silently override DR blockers."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import json

import pytest

from magazyn import backup, release_gate
from test_backup import backup_context, fake_globalnas
from test_magazyn import scenario  # fixture dependency for backup_context


@pytest.fixture
def prepared(backup_context, tmp_path, monkeypatch):
    client, store, head, admin, worker, item, private, spool, key = backup_context
    nas=fake_globalnas(tmp_path,monkeypatch)
    config={"db":Path(store.path),
            "spool":spool, "key_file":key, "mount":nas}
    created=backup.create_local(store.path,spool,key)
    assert created
    assert backup.flush_to_nas(spool,nas,key)["pending"]==0
    now=datetime.now(timezone.utc)
    backup._update_status(spool,bridge_health="PASS",
                          bridge_last_snapshot_at=now.isoformat(),
                          last_synced_at=now.isoformat())
    statuses=tmp_path/"stage-k-status"
    statuses.mkdir()
    (statuses/"daily.json").write_text(json.dumps({
        "status":"PASS","completed_at":now.isoformat()}))
    (statuses/"weekly.json").write_text(json.dumps({
        "status":"PASS","completed_at":now.isoformat(),
        "restore_validation":{k:{"status":"PASS"} for k in
                              release_gate.REQUIRED_WEEKLY_RESTORE}}))
    junit=tmp_path/"pytest.xml"
    junit.write_text('<testsuite name="magazyn" tests="203" failures="0" errors="0" skipped="0"/>')
    return config,statuses,junit,now


def test_gate_blocks_without_offsite_and_employee_and_daily_timer(prepared):
    config,stage_k,junit,now=prepared
    result=release_gate.production_readiness(config,stage_k,at=now,junit=junit)
    assert result["decision"]=="NO_GO"
    for key in ("sqlite","magazyn_backup","stage_k_daily","stage_k_weekly","pytest"):
        assert result["checks"][key]["status"]=="PASS",key
    for key in ("offsite_recovery","daily_timer","employee_access"):
        assert result["checks"][key]["status"]=="BLOCKED",key


def test_stagek_weekly_failure_blocks_even_when_all_other_flags_have_pass(prepared):
    config,stage_k,junit,now=prepared
    (stage_k/"weekly.json").write_text(json.dumps({
        "status":"FAIL","error":"knowledge_backup failed rc=1"}))
    recovery=config["mount"]/"Magazyn"/"recovery"
    recovery.mkdir(parents=True,exist_ok=True)
    (recovery/"magazyn-v1-aes256-key-offline.age").write_bytes(
        b"age-encryption.org/v1\n"+b"x"*150)
    result=release_gate.production_readiness(
        config,stage_k,at=now,junit=junit,offhost_drill_verified=True,
        daily_timer_verified=True,employee_acl_verified=True)
    assert result["decision"]=="NO_GO"
    assert result["checks"]["stage_k_weekly"]["status"]=="BLOCKED"
    assert result["checks"]["offsite_recovery"]["status"]=="PASS"


def test_weekly_restore_failure_blocks_even_with_weekly_backup_pass(prepared):
    config,stage_k,junit,now=prepared
    path=stage_k/"weekly.json"
    status=json.loads(path.read_text())
    status["restore_validation"]["adapters"]["status"]="FAIL"
    path.write_text(json.dumps(status))
    result=release_gate.production_readiness(config,stage_k,at=now,junit=junit)
    assert result["checks"]["stage_k_weekly"]["status"]=="BLOCKED"


def test_old_or_pending_backup_blocks_release(prepared):
    config,stage_k,junit,now=prepared
    backup._update_status(config["spool"],bridge_last_snapshot_at=(
        now-timedelta(hours=45)).isoformat(),bridge_health="DEGRADED")
    result=release_gate.production_readiness(config,stage_k,at=now,junit=junit)
    assert result["checks"]["magazyn_backup"]["status"]=="BLOCKED"


def test_release_gate_happy_path_requires_all_explicit_signoffs(prepared):
    config,stage_k,junit,now=prepared
    recovery=config["mount"]/"Magazyn"/"recovery"
    recovery.mkdir(parents=True,exist_ok=True)
    archive=recovery/"magazyn-v1-aes256-key-offline.age"
    archive.write_bytes(b"age-encryption.org/v1\n"+b"x"*145)
    result=release_gate.production_readiness(
        config,stage_k,at=now,junit=junit,
        offhost_drill_verified=True,
        daily_timer_verified=True,employee_acl_verified=True)
    assert result["decision"]=="GO"
    assert all(x["status"]=="PASS" for x in result["checks"].values())
    archive.write_bytes(b"plain-secret-not-age")
    assert release_gate.check_offhost(config,True)["status"]=="BLOCKED"


def test_test_report_must_be_complete(prepared):
    config,stage_k,junit,now=prepared
    junit.write_text('<testsuite tests="220" failures="1" errors="0"/>')
    assert release_gate.production_readiness(
        config,stage_k,at=now,junit=junit)["checks"]["pytest"]["status"]=="BLOCKED"
