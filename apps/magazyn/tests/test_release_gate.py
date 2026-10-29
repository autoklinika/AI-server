"""Release gate synthetic tests: automated conditions never silently override DR blockers."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import hashlib
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


def test_stagek_weekly_failure_blocks_even_when_all_other_flags_have_pass(accepted_yubikeys):
    config,stage_k,junit,now,*_ = accepted_yubikeys
    (stage_k/"weekly.json").write_text(json.dumps({
        "status":"FAIL","error":"knowledge_backup failed rc=1"}))
    result=dual_signoff(accepted_yubikeys)
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


def test_release_gate_happy_path_requires_all_explicit_signoffs(accepted_yubikeys):
    config,stage_k,junit,now,*_ = accepted_yubikeys
    result=dual_signoff(accepted_yubikeys)
    assert result["decision"]=="GO"
    assert all(x["status"]=="PASS" for x in result["checks"].values())
    archive=config["mount"]/"Magazyn"/"recovery"/"magazyn-v1-aes256-key-yubikey-spare.age"
    archive.write_bytes(b"not-encrypted")
    assert dual_signoff(accepted_yubikeys)["checks"]["offsite_recovery"]["status"]=="BLOCKED"


def test_test_report_must_be_complete(prepared):
    config,stage_k,junit,now=prepared
    junit.write_text('<testsuite tests="220" failures="1" errors="0"/>')
    assert release_gate.production_readiness(
        config,stage_k,at=now,junit=junit)["checks"]["pytest"]["status"]=="BLOCKED"


@pytest.fixture
def accepted_yubikeys(prepared, tmp_path):
    """Two independent synthetic recovery recipients with a restore report."""
    config, stage_k, junit, now = prepared
    main = tmp_path/"primary-recipient.txt"
    first = "age1yubikey1" + "a"*55
    second = "age1yubikey1" + "b"*55
    main.write_text(first+"\n")
    spare = config["key_file"].parent.parent/"yubikey-spare"/"recipient.txt"
    spare.parent.mkdir(mode=0o700)
    spare.write_text(second+"\n")
    spare.chmod(0o600)
    folder = config["mount"]/"Magazyn"/"recovery"
    folder.mkdir(parents=True, exist_ok=True)
    old = folder/"magazyn-v1-aes256-key-yubikey.age"
    new = folder/"magazyn-v1-aes256-key-yubikey-spare.age"
    header = b"age-encryption.org/v1\n-> piv-p256 "
    old.write_bytes(header+b"a"*180)
    new.write_bytes(header+b"b"*180)
    archive = next((config["mount"]/"Magazyn"/"daily").glob("*.mgzb"))
    report = tmp_path/"physical-drill.json"
    evidence = {
        "event": "PHYSICAL_SECOND_YUBIKEY_RECOVERY_DRILL",
        "status": "PASS",
        "at_utc": now.isoformat(),
        "production_sqlite_modified": False,
        "primary_recipient_sha256": hashlib.sha256(first.encode()).hexdigest(),
        "secondary_recipient_sha256": hashlib.sha256(second.encode()).hexdigest(),
        "secondary_ciphertext_sha256": hashlib.sha256(new.read_bytes()).hexdigest(),
        "source_archive_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
    }
    evidence["checks"] = [
        "recipient_distinct", "piv_nondefault", "physical_age_decrypt",
        "master_aes_identical", "nas_archive_verified",
        "sqlite_restored_in_ram", "document_hashes_valid",
    ]
    report.write_text(json.dumps(evidence))
    report.chmod(0o600)
    return config, stage_k, junit, now, main, spare, report


def dual_signoff(accepted_yubikeys, **updates):
    config, stage_k, junit, now, main, spare, report = accepted_yubikeys
    args = dict(at=now, junit=junit, primary_yubikey_drill_verified=True,
                spare_yubikey_drill_report=report,
                primary_recipient_file=main, spare_recipient_file=spare,
                daily_timer_verified=True, employee_acl_verified=True)
    args.update(updates)
    return release_gate.production_readiness(config, stage_k, **args)


def test_dual_yubikey_requires_first_physical_attestation(accepted_yubikeys):
    x=dual_signoff(accepted_yubikeys,primary_yubikey_drill_verified=False)
    assert x["decision"]=="NO_GO"
    assert x["checks"]["offsite_recovery"]["status"]=="BLOCKED"


def test_dual_yubikey_requires_real_second_drill_report(accepted_yubikeys):
    x=dual_signoff(accepted_yubikeys,spare_yubikey_drill_report=None)
    assert x["checks"]["offsite_recovery"]["status"]=="BLOCKED"


def test_dual_yubikey_rejects_duplicate_public_recipients(accepted_yubikeys):
    _,_,_,_,main,spare,_=accepted_yubikeys
    spare.write_bytes(main.read_bytes())
    assert dual_signoff(accepted_yubikeys)["checks"]["offsite_recovery"]["status"]=="BLOCKED"


def test_dual_yubikey_rejects_altered_escrow_hash(accepted_yubikeys):
    config,_,_,_,_,_,_=accepted_yubikeys
    p=config["mount"]/"Magazyn"/"recovery"/"magazyn-v1-aes256-key-yubikey-spare.age"
    p.write_bytes(p.read_bytes()+b"tampered")
    assert dual_signoff(accepted_yubikeys)["checks"]["offsite_recovery"]["status"]=="BLOCKED"


def test_dual_yubikey_rejects_incomplete_physical_drill(accepted_yubikeys):
    *_,report=accepted_yubikeys
    data=json.loads(report.read_text())
    data["checks"].remove("sqlite_restored_in_ram")
    report.write_text(json.dumps(data))
    assert dual_signoff(accepted_yubikeys)["checks"]["offsite_recovery"]["status"]=="BLOCKED"


def test_dual_yubikey_rejects_unprotected_physical_report(accepted_yubikeys):
    *_,report=accepted_yubikeys
    report.chmod(0o644)
    assert dual_signoff(accepted_yubikeys)["checks"]["offsite_recovery"]["status"]=="BLOCKED"


def test_dual_yubikey_rejects_claim_of_production_modification(accepted_yubikeys):
    *_,report=accepted_yubikeys
    data=json.loads(report.read_text())
    data["production_sqlite_modified"]=True
    report.write_text(json.dumps(data))
    assert dual_signoff(accepted_yubikeys)["checks"]["offsite_recovery"]["status"]=="BLOCKED"
