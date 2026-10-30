"""Admin restore drills, archive selectors, and history filters (synthetic data only)."""
from datetime import date
from pathlib import Path

import pytest

from magazyn import backup
from test_magazyn import scenario, auth, ecu, operation
from test_backup import fake_globalnas


@pytest.fixture
def private_backup(scenario, tmp_path, monkeypatch):
    client, store, admin, worker = scenario
    key = backup.init_key(tmp_path / "key-private" / "secret.key")
    spool = tmp_path / "private-spool"
    mount = tmp_path / "offline-nas"
    mount.mkdir()
    monkeypatch.setenv("MAGAZYN_BACKUP_SPOOL", str(spool))
    monkeypatch.setenv("MAGAZYN_BACKUP_KEY_FILE", str(key))
    monkeypatch.setenv("MAGAZYN_BACKUP_MOUNT", str(mount))
    return client, store, admin, worker, key, spool, mount


def test_admin_list_and_restore_local_archive_in_ram(private_backup):
    c, store, admin, worker, key, spool, mount = private_backup
    assert c.get("/api/backup/archives").status_code == 401
    headers = auth(c)
    loc = store.add_location("A1")
    item = store.add_item(ecu(), {"id": admin, "username": "admin1", "role": "admin"})
    store.stock_operation(operation(item, loc, quantity=4),
                          {"id": admin, "username": "admin1", "role": "admin"})
    name = Path(backup.create_local(store.path, spool, key)[0]).name
    listed = c.get("/api/backup/archives")
    assert listed.status_code == 200 and not listed.json()["nas_online"]
    assert listed.json()["archives"][0]["name"] == name
    request = {"source": "local", "tier": "daily", "name": name}
    assert c.post("/api/backup/restore-check", json=request).status_code == 403
    response = c.post("/api/backup/restore-check", json=request, headers=headers)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "PASS"
    assert response.json()["temporary_plaintext_removed"]
    assert store.item(item)["total"] == 4
    assert len(store.history()) == 1
    assert not list(Path("/dev/shm").glob("magazyn-restore-check-*"))


def test_automated_nas_archive_drill_and_auth(private_backup, monkeypatch, tmp_path):
    c, store, admin, worker, key, spool, mount = private_backup
    h = auth(c)
    local = Path(backup.create_local(store.path, spool, key)[0])
    nas = fake_globalnas(tmp_path, monkeypatch)
    monkeypatch.setenv("MAGAZYN_BACKUP_MOUNT", str(nas))
    backup.flush_to_nas(spool, nas, key)
    assert not local.exists()
    rows = c.get("/api/backup/archives").json()
    assert rows["nas_online"] and rows["archives"][0]["source"] == "nas"
    request = {"source": "nas", "tier": "daily", "name": local.name}
    got = c.post("/api/backup/restore-check", json=request, headers=h)
    assert got.status_code == 200 and got.json()["integrity"] == "ok"

    auth(c, "worker1", "second-test-password-456")
    assert c.get("/api/backup/archives").status_code == 403
    assert c.post("/api/backup/restore-check", json=request, headers=h).status_code == 403


@pytest.mark.parametrize("bad", (
    {"source": "nas", "tier": "..", "name": "x.mgzb"},
    {"source": "nas", "tier": "daily", "name": "../MAGAZYN.sqlite3"},
    {"source": "external", "tier": "daily", "name": "20261027T000000Z-12345678.mgzb"},
))
def test_restore_rejects_path_and_source_injection(private_backup, bad):
    c, *_ = private_backup
    h = auth(c)
    assert c.post("/api/backup/restore-check", json=bad, headers=h).status_code in (422, 503)


def test_restore_rejects_modified_ciphertext(private_backup):
    c, store, admin, worker, key, spool, mount = private_backup
    h = auth(c)
    path = Path(backup.create_local(store.path, spool, key)[0])
    data = bytearray(path.read_bytes())
    data[-1] ^= 1
    path.write_bytes(data)
    result = c.post("/api/backup/restore-check", json={
        "source": "local", "tier": "daily", "name": path.name}, headers=h)
    assert result.status_code == 503
    assert store.statistics()["items"] == 0


def test_history_filters_by_user_product_date_and_admin_can_edit(scenario):
    c, s, admin, worker = scenario
    h = auth(c)
    loc = s.add_location("A1")
    actor_admin = {"id": admin, "username": "admin1", "role": "admin"}
    actor_worker = {"id": worker, "username": "worker1", "role": "user"}
    item = s.add_item(ecu(), actor_admin)
    old = s.stock_operation(operation(item, loc, quantity=5), actor_admin)["event_id"]
    new = s.stock_operation(operation(item, loc, action="issue",
                                     quantity=1, reason="sale"), actor_worker)["event_id"]
    assert c.patch(f"/api/history/{old}", headers=h, json={
        "created_at": "2026-09-20T10:00:00+00:00",
        "note": "admin revised",
    }).status_code == 200

    assert [r["id"] for r in c.get("/api/history", params={"date_from": "2026-10-01"}).json()] == [new]
    assert [r["id"] for r in c.get("/api/history", params={"date_to": "2026-09-30"}).json()] == [old]
    assert [r["id"] for r in c.get("/api/history", params={"actor_id": worker}).json()] == [new]
    assert len(c.get("/api/history", params={"q": "edc7"}).json()) == 2
    assert len(c.get("/api/history", params={"q": "nonexistent"}).json()) == 0
    assert c.get("/api/history", params={
        "date_from": "2026-10-02", "date_to": "2026-10-01"}).status_code == 422
    assert c.get("/api/history", params={"date_from": "invalid-date"}).status_code == 422
    before=s.item(item)["total"]
    assert c.patch(f"/api/history/{old}", json={"quantity": 7}, headers=h).status_code == 200
    assert s.item(item)["total"] == before


def test_new_admin_ui_controls_and_old_theme_unchanged(scenario):
    c, *_ = scenario
    html = c.get("/").text
    for ident in ("history-filters", "history-edit-dialog", "backup-archives-refresh",
                  "backup-archive-select", "backup-restore-test"):
        assert f'id="{ident}"' in html
    js = c.get("/static/app.js").text
    assert "/api/backup/restore-check" in js
    assert "/api/history?" in js
    css = c.get("/static/style.css").text.lower()
    for color in ("#b74b0d", "#282d33", "#f5f5f4"):
        assert color in css


def test_secure_cookie_on_https_even_with_loopback_dev_fallback(tmp_path):
    from fastapi.testclient import TestClient
    from magazyn.server import create_app

    instance = create_app(str(tmp_path / "db" / "inventory.sqlite3"), secure_cookie=False)
    instance.state.store.create_user("owner", "long-test-password-123", "admin")
    with TestClient(instance, base_url="https://magazyn.test") as browser:
        result = browser.post("/api/auth/login", json={
            "username": "owner", "password": "long-test-password-123"})
        assert result.status_code == 200
        cookie = result.headers["set-cookie"]
        assert "secure" in cookie.lower()
        assert "httponly" in cookie.lower()
        assert "samesite=strict" in cookie.lower()
