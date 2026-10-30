"""Security regression for persistent HTTP login limits; synthetic accounts only."""
from concurrent.futures import ThreadPoolExecutor
import re
import time

import pytest
from fastapi.testclient import TestClient

from magazyn.server import create_app
from magazyn.store import (
    Store, Problem, AUTH_WINDOW_SECONDS, AUTH_BLOCK_SECONDS,
    AUTH_ACCOUNT_FAILURES, AUTH_CLIENT_FAILURES
)


@pytest.fixture
def fixture(tmp_path):
    path=tmp_path/"private"/"inventory.sqlite3"
    app=create_app(str(path),secure_cookie=False)
    s=app.state.store
    admin=s.create_user("admin1","sample-admin-password-123","admin")
    s.create_user("staff1","sample-staff-password-456","user")
    return TestClient(app),s,path,admin


def login(c, username="admin1", password="bad-password",
          headers=None):
    return c.post("/api/auth/login",
        json={"username":username,"password":password},headers=headers or {})


def test_http_rate_limit_and_retry_after_do_not_leak_login(fixture):
    c,s,path,admin=fixture
    for _ in range(AUTH_ACCOUNT_FAILURES-1):
        r=login(c)
        assert r.status_code==401
        assert r.json()=={"detail":"Nieprawidłowe dane logowania"}
    fifth=login(c)
    assert fifth.status_code==429
    assert 1<=int(fifth.headers["Retry-After"])<=AUTH_BLOCK_SECONDS
    assert "admin1" not in fifth.text
    blocked=login(c,password="sample-admin-password-123")
    assert blocked.status_code==429
    assert blocked.headers["Retry-After"]
    assert c.get("/api/auth/me").status_code==401
    with s.connect() as con:
        rows=con.execute("SELECT * FROM auth_login_throttles").fetchall()
        assert len(rows)==2
        assert all(re.fullmatch(r"[0-9a-f]{64}",row["key_hash"]) for row in rows)
        assert all("admin1" not in str(dict(row)) and
                   "testclient" not in str(dict(row)) for row in rows)


def test_throttle_is_persistent_across_store_reopen_and_expires(fixture):
    c,s,path,admin=fixture
    current=time.time()
    for n in range(AUTH_ACCOUNT_FAILURES):
        with pytest.raises(Problem) as exc:
            s.authenticate_login("admin1","incorrect","127.0.0.1",
                                 current_time=current+1+n)
        assert exc.value.status==(
            429 if n==AUTH_ACCOUNT_FAILURES-1 else 401)
    reopened=Store(str(path))
    with pytest.raises(Problem) as blocked:
        reopened.authenticate_login("admin1","sample-admin-password-123",
                                    "127.0.0.1",current_time=current+6)
    assert blocked.value.status==429
    assert blocked.value.retry_after>0
    accepted=reopened.authenticate_login(
        "admin1","sample-admin-password-123","127.0.0.1",
        current_time=current+AUTH_BLOCK_SECONDS+AUTH_ACCOUNT_FAILURES+5)
    assert accepted["id"]==admin
    with reopened.connect() as con:
        attempt_count=con.execute(
            "SELECT COUNT(*) FROM auth_login_throttles").fetchone()[0]
    assert attempt_count<=1


def test_success_resets_account_failures_without_invalidating_session(fixture):
    c,s,path,admin=fixture
    success=login(c,password="sample-admin-password-123")
    assert success.status_code==200
    csrf=success.json()["csrf"]
    cookie=success.cookies.get("magazyn_session")
    assert cookie and csrf
    for _ in range(AUTH_ACCOUNT_FAILURES-1):
        assert login(c).status_code==401
    assert login(c,password="sample-admin-password-123").status_code==200
    # The old authorized session remains valid and CSRF permissions do not change.
    assert s.session_user(cookie)["id"]==admin
    assert login(c).status_code==401
    assert c.get("/api/auth/me").status_code==200


def test_invalid_users_get_identical_error_and_rate_limit(fixture):
    c,s,path,admin=fixture
    assert login(c,"ghost-user").status_code==401
    assert login(c,"admin1").status_code==401
    for _ in range(AUTH_ACCOUNT_FAILURES-1):
        response=login(c,"ghost-user")
    assert response.status_code==429
    assert login(c,"ghost-user",password="arbitrary").status_code==429
    assert login(c,password="sample-admin-password-123").status_code==200
    # The admin works despite a different unknown name being blocked.


def test_x_forwarded_for_does_not_reset_throttle(fixture):
    c,s,path,admin=fixture
    for attempt in range(AUTH_ACCOUNT_FAILURES):
        forged={"X-Forwarded-For":f"203.0.113.{attempt+1}"}
        r=login(c,headers=forged)
    assert r.status_code==429
    assert login(c,password="sample-admin-password-123",
                 headers={"X-Forwarded-For":"198.51.100.15"}).status_code==429


def test_client_limit_blocks_username_spraying(tmp_path,monkeypatch):
    from magazyn import store as store_module
    s=Store(str(tmp_path/"db.sqlite3"))
    # Only for this synthetic test: avoid spending CPU on 30 separate scrypt calls.
    monkeypatch.setattr(store_module,"password_verify",lambda *_args:False)
    current=time.time()
    for attempt in range(AUTH_CLIENT_FAILURES):
        with pytest.raises(Problem) as exc:
            s.authenticate_login(f"unknown{attempt}","bad","peer-1",current_time=current)
        assert exc.value.status==(429 if attempt==AUTH_CLIENT_FAILURES-1 else 401)
    with pytest.raises(Problem) as blocked:
        s.authenticate_login("any-name","bad","peer-1",current_time=current)
    assert blocked.value.status==429
    # A different socket peer is not blocked by the original peer's spray.
    with pytest.raises(Problem) as independent:
        s.authenticate_login("any-name","bad","peer-2",current_time=current)
    assert independent.value.status==401


def test_concurrent_auth_attempts_are_serialized(tmp_path,monkeypatch):
    from magazyn import store as store_module
    db=str(tmp_path/"private"/"inventory.sqlite3")
    Store(db).create_user("admin1","sample-admin-password-123","admin")
    monkeypatch.setattr(store_module,"password_verify",lambda *_args:False)
    current=time.time()
    def attempt(_index):
        instance=Store(db)
        try:
            instance.authenticate_login("admin1","bad","peer-1",current_time=current)
        except Problem as error:
            return error.status
        return 200
    with ThreadPoolExecutor(max_workers=8) as pool:
        codes=list(pool.map(attempt,range(16)))
    assert codes.count(401)==AUTH_ACCOUNT_FAILURES-1
    assert codes.count(429)==16-(AUTH_ACCOUNT_FAILURES-1)
    with Store(db).connect() as con:
        row=con.execute(
            "SELECT failures FROM auth_login_throttles ORDER BY failures DESC LIMIT 1"
        ).fetchone()
    assert row and row["failures"]==AUTH_ACCOUNT_FAILURES


def test_active_cookie_remains_authorized_after_failed_attempts(fixture):
    c,s,path,admin=fixture
    r=login(c,password="sample-admin-password-123")
    token=r.cookies.get("magazyn_session")
    assert token
    for _ in range(AUTH_ACCOUNT_FAILURES):
        login(c,password="not-the-password")
    assert s.session_user(token)["id"]==admin
    assert c.get("/api/stats").status_code==200
