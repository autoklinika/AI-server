"""Production-specific display and Secure cookie enforcement, synthetic database."""
import pytest
from fastapi.testclient import TestClient
from magazyn.server import create_app


def test_production_title_health_and_secure_cookie(monkeypatch,tmp_path):
    monkeypatch.setenv("MAGAZYN_ENV","production")
    app=create_app(str(tmp_path/"prod.sqlite3"),secure_cookie=True)
    app.state.store.create_user("owner","synthetic-password-for-production","admin")
    with TestClient(app,base_url="https://magazyn.example.invalid") as client:
        page=client.get("/")
        assert page.status_code==200
        assert "MAGAZYN V1 · PRODUKCJA" in page.text
        assert 'class="dev-mark">DEV' not in page.text
        assert "ŚRODOWISKO DEV" not in page.text
        assert "Magazyn V1"==app.title
        assert client.get("/healthz").json()=={
            "status":"ok","service":"magazyn","environment":"production"}
        signed=client.post("/api/auth/login",json={
            "username":"owner","password":"synthetic-password-for-production"})
        assert signed.status_code==200
        cookie=signed.headers["set-cookie"].lower()
        assert "secure" in cookie and "httponly" in cookie and "samesite=strict" in cookie
        assert client.get("/api/auth/me").json()["role"]=="admin"


def test_production_refuses_unsafe_cookies(monkeypatch,tmp_path):
    monkeypatch.setenv("MAGAZYN_ENV","production")
    with pytest.raises(RuntimeError,match="Secure"):
        create_app(str(tmp_path/"unsafe.sqlite3"),secure_cookie=False)


def test_dev_still_displays_dev_and_accepts_loopback_test(monkeypatch,tmp_path):
    monkeypatch.delenv("MAGAZYN_ENV",raising=False)
    app=create_app(str(tmp_path/"dev.sqlite3"),secure_cookie=False)
    with TestClient(app) as client:
        assert "MAGAZYN V1 · ŚRODOWISKO DEV" in client.get("/").text
        assert 'class="dev-mark">DEV' in client.get("/").text
        assert client.get("/healthz").json()["service"]=="magazyn-dev"


def test_environment_must_be_known(monkeypatch,tmp_path):
    monkeypatch.setenv("MAGAZYN_ENV","maybe-production")
    with pytest.raises(RuntimeError,match="MAGAZYN_ENV"):
        create_app(str(tmp_path/"unknown.sqlite3"))
