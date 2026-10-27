"""Encrypted backup and GlobalNAS guard tests; fake NAS is never a real mount."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from magazyn import backup
from magazyn.store import Store
from test_magazyn import scenario, auth, ecu, operation, post


@pytest.fixture
def backup_context(scenario, tmp_path):
    c, s, admin, worker = scenario
    heads = auth(c)
    loc = s.add_location("A1")
    item = s.add_item(ecu(), {"id": admin, "username": "admin1", "role": "admin"})
    s.stock_operation(operation(item, loc, quantity=5), {
        "id": admin, "username": "admin1", "role": "admin"})
    private = tmp_path / "private-backup"
    private.mkdir(mode=0o700)
    spool = private / "spool"
    keys = private / "secrets"
    key_file = backup.init_key(keys / "magazyn.key")
    return c, s, heads, admin, worker, item, private, spool, key_file


def fake_globalnas(tmp_path, monkeypatch):
    root = tmp_path / "GlobalNAS-fake"
    root.mkdir(mode=0o700)
    (root / ".ai-platform-backup-target.json").write_text(
        '{"schema_version":1,"purpose":"ai-platform-stage-k",'
        '"nas":"GlobalNAS","host":"globalnas.local","share":"AI_Platform"}', encoding="utf-8")
    original = backup.os.path.ismount
    monkeypatch.setattr(backup.os.path, "ismount", lambda p: Path(p) == root or original(p))
    monkeypatch.setattr(backup.subprocess, "run",
                        lambda *args, **kwargs: SimpleNamespace(
                            stdout="cifs //globalnas.local/AI_Platform\n"))
    return root


def test_encrypted_snapshot_restore_and_integrity(backup_context):
    c, s, h, admin, worker, item, private, spool, key = backup_context
    result = backup.create_local(s.path, spool, key)
    assert len(result) == 1
    archive = Path(result[0])
    assert archive.stat().st_mode & 0o777 == 0o600
    raw = archive.read_bytes()
    assert raw.startswith(backup.MAGIC)
    assert b"Bosch EDC7" not in raw
    verified = backup.verify_archive(archive, key)
    assert verified["status"] == "PASS"
    destination = private / "restored" / "magazyn.sqlite3"
    restored = backup.restore_archive(archive, destination, key)
    assert restored["status"] == "PASS"
    assert destination.exists() and destination.stat().st_mode & 0o777 == 0o600
    copy = Store(str(destination))
    assert copy.item(item)["total"] == 5
    assert copy.users()[0]["username"] in ("admin1", "worker1")
    assert len(copy.history()) == 1
    with pytest.raises(backup.BackupFailure, match="nigdy nie nadpisuje"):
        backup.restore_archive(archive, destination, key)


def test_wrong_key_and_tamper_detected(backup_context):
    c, s, h, admin, worker, item, private, spool, key = backup_context
    archive = Path(backup.create_local(s.path, spool, key)[0])
    different = backup.init_key(private / "different" / "key.bin")
    with pytest.raises(backup.BackupFailure, match="klucz"):
        backup.verify_archive(archive, different)
    damaged = private / "damage.mgzb"
    raw = bytearray(archive.read_bytes())
    raw[-1] ^= 1
    damaged.write_bytes(raw)
    with pytest.raises(backup.BackupFailure, match="klucz lub"):
        backup.verify_archive(damaged, key)


def test_pending_without_globalnas_does_not_disappear(backup_context, tmp_path):
    c, s, h, admin, worker, item, private, spool, key = backup_context
    archive = Path(backup.create_local(s.path, spool, key)[0])
    not_mounted = tmp_path / "not-mounted"
    not_mounted.mkdir()
    with pytest.raises(backup.BackupFailure, match="nie jest zamontowany"):
        backup.flush_to_nas(spool, not_mounted, key)
    assert archive.exists()
    assert backup.status(spool)["pending"] == 1


def test_flush_to_verified_fake_nas_and_retention(backup_context, tmp_path, monkeypatch):
    c, s, h, admin, worker, item, private, spool, key = backup_context
    start = datetime(2026, 10, 1, 6, tzinfo=timezone.utc)
    created = []
    for i in range(8):
        created.extend(backup.create_local(s.path, spool, key,
                            captured_at=start + timedelta(days=i)))
    assert backup.status(spool)["pending"] == 8
    mount = fake_globalnas(tmp_path, monkeypatch)
    summary = backup.flush_to_nas(spool, mount, key)
    assert summary == {"uploaded":8,"pending":0}
    copied = sorted((mount / "Magazyn" / "daily").glob("*.mgzb"))
    assert len(copied) == 7
    assert backup.verify_archive(copied[-1],key)["status"] == "PASS"
    assert backup.status(spool)["last_synced_at"]
    assert all(not Path(p).exists() for p in created)


def test_daily_tier_schedule_and_status(backup_context):
    c, s, h, admin, worker, item, private, spool, key = backup_context
    assert backup.status(spool)["configured"] is False
    # First of month and Sunday: same snapshot in daily, weekly, monthly.
    names = backup.daily_local(s.path, spool, key,
        captured_at=datetime(2026,11,1,10,tzinfo=timezone.utc))
    assert len(names)==3
    assert {Path(p).parent.name for p in names}=={"daily","weekly","monthly"}
    assert backup.status(spool)["pending"]==3


def test_key_protection_and_no_replacement(backup_context, tmp_path):
    c, s, h, admin, worker, item, private, spool, key = backup_context
    assert key.stat().st_mode & 0o777 == 0o600
    with pytest.raises(backup.BackupFailure, match="już istnieje"):
        backup.init_key(key)
    insecure = private / "bad.key"
    insecure.write_bytes(b"A"*32)
    insecure.chmod(0o644)
    with pytest.raises(backup.BackupFailure, match="0600"):
        backup.read_key(insecure)
    link = private / "key-symlink"
    link.symlink_to(key)
    with pytest.raises(backup.BackupFailure, match="dowiązania"):
        backup.read_key(link)


def test_local_spool_limit_does_not_delete_existing_archives(backup_context):
    c, s, h, admin, worker, item, private, spool, key = backup_context
    archive = Path(backup.create_local(s.path, spool, key)[0])
    with pytest.raises(backup.BackupFailure, match="bufor pełny"):
        backup.create_local(s.path, spool, key, max_spool_bytes=1)
    assert archive.exists() and backup.status(spool)["pending"] == 1


def test_incorrect_globalnas_marker_rejected(backup_context, tmp_path, monkeypatch):
    c, s, h, admin, worker, item, private, spool, key = backup_context
    archive = Path(backup.create_local(s.path, spool, key)[0])
    root = fake_globalnas(tmp_path, monkeypatch)
    (root / ".ai-platform-backup-target.json").write_text(
        '{"schema_version":1,"purpose":"other-nas","nas":"Other","share":"AI_Platform"}')
    with pytest.raises(backup.BackupFailure,match="nieoczekiwany"):
        backup.flush_to_nas(spool, root, key)
    assert archive.exists()


def test_manual_backup_api_admin_only_and_status(backup_context, monkeypatch):
    c, s, h, admin, worker, item, private, spool, key = backup_context
    assert c.get("/api/backup/status").json()["configured"] is False
    assert c.post("/api/backup/manual",json={},headers=h).status_code==503
    monkeypatch.setenv("MAGAZYN_BACKUP_SPOOL",str(spool))
    monkeypatch.setenv("MAGAZYN_BACKUP_KEY_FILE",str(key))
    assert c.get("/api/backup/status").json()["configured"] is False
    assert c.post("/api/backup/manual",json={}).status_code==403
    result = c.post("/api/backup/manual",json={},headers=h)
    assert result.status_code==201, result.text
    assert result.json()["pending"]==1
    assert c.get("/api/backup/status").json()["pending"]==1
    worker_h = auth(c,"worker1","second-test-password-456")
    assert c.get("/api/backup/status").status_code == 403
    assert c.post("/api/backup/manual",json={},headers=worker_h).status_code == 403


def test_invalid_database_snapshot_rejected(tmp_path):
    root=tmp_path/"root"
    root.mkdir(mode=0o700)
    key=backup.init_key(root/"key")
    foreign=root/"foreign.sqlite3"
    import sqlite3
    con=sqlite3.connect(foreign)
    con.execute("CREATE TABLE unrelated(id INTEGER)")
    con.commit()
    con.close()
    with pytest.raises(backup.BackupFailure,match="nie jest bazą"):
        backup.create_local(foreign,root/"spool",key)



def test_systemd_automount_and_cifs_stack_is_accepted(backup_context, tmp_path, monkeypatch):
    c, s, h, admin, worker, item, private, spool, key = backup_context
    archive=Path(backup.create_local(s.path,spool,key)[0])
    mount=fake_globalnas(tmp_path,monkeypatch)
    monkeypatch.setattr(backup.subprocess,"run",lambda *args,**kwargs:SimpleNamespace(
        stdout="autofs systemd-1\ncifs //globalnas.local/AI_Platform\n"))
    result=backup.flush_to_nas(spool,mount,key)
    assert result=={"uploaded":1,"pending":0}
    assert not archive.exists()
    assert len(list((mount/"Magazyn"/"daily").glob("*.mgzb")))==1


def test_systemd_automount_alone_does_not_allow_nas_write(backup_context,tmp_path,monkeypatch):
    c, s, h, admin, worker, item, private, spool, key = backup_context
    archive=Path(backup.create_local(s.path,spool,key)[0])
    mount=fake_globalnas(tmp_path,monkeypatch)
    monkeypatch.setattr(backup.subprocess,"run",lambda *args,**kwargs:SimpleNamespace(
        stdout="autofs systemd-1\n"))
    with pytest.raises(backup.BackupFailure,match="nieoczekiwany"):
        backup.flush_to_nas(spool,mount,key)
    assert archive.exists()
    assert not (mount/"Magazyn").exists()


def test_unexpected_top_layer_blocks_even_if_cifs_underneath(backup_context,tmp_path,monkeypatch):
    c, s, h, admin, worker, item, private, spool, key = backup_context
    archive=Path(backup.create_local(s.path,spool,key)[0])
    mount=fake_globalnas(tmp_path,monkeypatch)
    monkeypatch.setattr(backup.subprocess,"run",lambda *args,**kwargs:SimpleNamespace(
        stdout="cifs //globalnas.local/AI_Platform\nfuse.sshfs unexpected\n"))
    with pytest.raises(backup.BackupFailure,match="nieoczekiwany"):
        backup.flush_to_nas(spool,mount,key)
    assert archive.exists()
    assert not (mount/"Magazyn").exists()
