"""Stage K bridge tests use synthetic Magazyn DBs and fake NAS only."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

import pytest

from magazyn import backup, stage_k_bridge as bridge
from test_backup import backup_context, fake_globalnas
from test_magazyn import scenario  # fixture dependency of backup_context


def configuration(backup_context, tmp_path):
    c, store, h, admin, worker, item, private, spool, key = backup_context
    offline = tmp_path / "offline-nas"
    offline.mkdir()
    return {"db": Path(store.path), "spool": spool, "key_file": key, "mount": offline}


def test_nas_outage_preserves_snapshot_then_hourly_retry_flushes(backup_context, tmp_path, monkeypatch):
    cfg = configuration(backup_context, tmp_path)
    now = datetime(2026, 10, 27, 9, tzinfo=timezone.utc)
    failed = bridge.execute("cycle", cfg, at=now)
    assert failed["status"] == "DEGRADED"
    assert failed["created"] == 1 and failed["uploaded"] == 0 and failed["pending"] == 1
    assert "GlobalNAS" in backup.status(cfg["spool"])["last_error"]

    repeat = bridge.execute("cycle", cfg, at=now + timedelta(minutes=10))
    assert repeat["created"] == 0 and repeat["pending"] == 1

    cfg["mount"] = fake_globalnas(tmp_path, monkeypatch)
    repaired = bridge.execute("retry", cfg, at=now + timedelta(hours=1))
    assert repaired["status"] == "PASS"
    assert repaired["pending"] == 0 and repaired["uploaded"] == 1
    target = list((cfg["mount"] / "Magazyn" / "daily").glob("*.mgzb"))
    assert len(target) == 1
    assert backup.verify_archive(target[0], cfg["key_file"])["status"] == "PASS"
    restored = cfg["spool"].parent / "restored" / "snapshot.sqlite3"
    assert backup.restore_archive(target[0], restored, cfg["key_file"])["status"] == "PASS"
    assert restored.is_file()


def test_weekly_monthly_and_same_day_idempotence(backup_context, tmp_path, monkeypatch):
    cfg = configuration(backup_context, tmp_path)
    cfg["mount"] = fake_globalnas(tmp_path, monkeypatch)
    now = datetime(2026, 11, 1, 10, tzinfo=timezone.utc)  # Sunday and 1st
    first = bridge.execute("cycle", cfg, at=now)
    second = bridge.execute("cycle", cfg, at=now + timedelta(hours=1))
    assert first["status"] == "PASS" and first["created"] == 3
    assert first["uploaded"] == 3
    assert second["status"] == "PASS" and second["created"] == 0
    for tier in backup.TIERS:
        assert len(list((cfg["mount"] / "Magazyn" / tier).glob("*.mgzb"))) == 1
    assert backup.status(cfg["spool"])["bridge_last_snapshot_date"] == "2026-11-01"


def test_snapshot_failure_does_not_block_previous_pending_flush(backup_context, tmp_path, monkeypatch):
    cfg = configuration(backup_context, tmp_path)
    now = datetime(2026, 10, 27, 10, tzinfo=timezone.utc)
    bridge.execute("cycle", cfg, at=now)
    assert backup.status(cfg["spool"])["pending"] == 1
    cfg["mount"] = fake_globalnas(tmp_path, monkeypatch)
    cfg["db"] = tmp_path / "missing.sqlite3"
    failed = bridge.execute("cycle", cfg, at=now + timedelta(days=1))
    assert failed["status"] == "FAIL"
    assert failed["uploaded"] == 1 and failed["pending"] == 0
    assert backup.status(cfg["spool"])["bridge_last_snapshot_date"] == "2026-10-27"


def test_hourly_health_detects_stale_backup(backup_context, tmp_path, monkeypatch):
    cfg = configuration(backup_context, tmp_path)
    cfg["mount"] = fake_globalnas(tmp_path, monkeypatch)
    now = datetime(2026, 10, 27, 9, tzinfo=timezone.utc)
    assert bridge.execute("cycle", cfg, at=now)["status"] == "PASS"
    stale = bridge.execute("retry", cfg, at=now + timedelta(hours=37))
    assert stale["status"] == "FAIL"
    assert any("36 godzin" in issue for issue in stale["issues"])
    assert backup.status(cfg["spool"])["bridge_health"] == "FAIL"


def test_secure_config_rejects_loose_permissions_and_symlink(backup_context, tmp_path):
    cfg = configuration(backup_context, tmp_path)
    config_path = tmp_path / "magazyn-bridge.json"
    config_path.write_text(json.dumps({k: str(v) for k, v in cfg.items()}))
    config_path.chmod(0o600)
    assert bridge.read_config(config_path) == cfg
    config_path.chmod(0o644)
    with pytest.raises(bridge.BridgeFailure, match="0600"):
        bridge.read_config(config_path)
    config_path.chmod(0o600)
    link = tmp_path / "config-link"
    link.symlink_to(config_path)
    with pytest.raises(bridge.BridgeFailure, match="dowiązaniem"):
        bridge.read_config(link)


def test_config_cannot_keep_working_data_on_globalnas(backup_context, tmp_path):
    cfg = configuration(backup_context, tmp_path)
    cfg["spool"] = cfg["mount"] / "spool"
    path = tmp_path / "magazyn-bridge.json"
    path.write_text(json.dumps({k: str(v) for k, v in cfg.items()}))
    path.chmod(0o600)
    with pytest.raises(bridge.BridgeFailure, match="GlobalNAS"):
        bridge.read_config(path)


def test_lock_prevents_concurrent_bridge_cycles(backup_context, tmp_path):
    cfg = configuration(backup_context, tmp_path)
    spool = backup._secure_dir(cfg["spool"])
    fd = bridge._acquire_lock(spool)
    assert fd is not None
    try:
        assert bridge.execute("cycle", cfg)["status"] == "BUSY"
        assert backup.status(spool)["pending"] == 0
    finally:
        import os
        os.close(fd)


def test_cli_returns_nonzero_for_offline_nas(backup_context, tmp_path, capsys):
    cfg = configuration(backup_context, tmp_path)
    path = tmp_path / "magazyn-bridge.json"
    path.write_text(json.dumps({k: str(v) for k, v in cfg.items()}))
    path.chmod(0o600)
    assert bridge.main(["cycle", "--config", str(path)]) == 2
    answer = json.loads(capsys.readouterr().out)
    assert answer["status"] == "DEGRADED" and answer["pending"] == 1


def test_pending_older_than_day_is_reported(backup_context, tmp_path):
    import os

    cfg = configuration(backup_context, tmp_path)
    now = datetime(2026, 10, 27, 12, tzinfo=timezone.utc)
    assert bridge.execute("cycle", cfg, at=now)["pending"] == 1
    pending_file = next((cfg["spool"] / "daily").glob("*.mgzb"))
    previous = now.timestamp() - 30 * 3600
    os.utime(pending_file, (previous, previous))
    checked = bridge.execute("retry", cfg, at=now + timedelta(hours=1))
    assert checked["status"] == "DEGRADED"
    assert any("24 godziny" in issue for issue in checked["issues"])
    assert backup.status(cfg["spool"])["bridge_oldest_pending_hours"] >= 30
