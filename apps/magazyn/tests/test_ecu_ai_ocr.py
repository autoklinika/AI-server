"""Regression tests for opt-in ECU image AI. Never contacts GPU or production."""
import base64

from fastapi.testclient import TestClient

from magazyn import ecu_ai
from magazyn.server import create_app


def jpg():
    # Test-only magic, not a photograph; model call always mocked.
    return base64.b64encode(b"\xff\xd8\xff" + b"A" * 90 + b"\xff\xd9").decode()


def test_ai_and_android_agree_on_bosch():
    result = ecu_ai.analyze_transcripts(
        "BOSCH\n0 281 016 738\nEDC17C46\nHW: H1\nSW: S3",
        "0 281 016 738\nHW: H1\nSW: S3",
        ["0281016738"],
    )
    assert result["primaryNumber"] == "0281016738"
    assert result["manufacturer"] == "Bosch"
    assert result["hardware"] == "H1"
    assert result["software"] == "S3"
    assert result["model"] == "EDC17C46"
    assert result["evidence"] == "barcode_and_ocr"
    assert result["warnings"] == []


def test_ai_phone_conflict_blocks_prefill():
    result = ecu_ai.analyze_transcripts(
        "BOSCH\n0 281 016 738",
        "BOSCH\n0 281 016 739",
        [],
    )
    assert result["primaryNumber"] == ""
    assert result["candidates"] == ["0281016738", "0281016739"]
    assert result["warnings"]


def test_serial_or_barcode_not_unverified_product_number():
    result = ecu_ai.analyze_transcripts(
        "Continental\nS/N: 987654321\nHW: 01",
        "Serial 987654321",
        ["987654321"],
    )
    assert result["primaryNumber"] == ""
    assert result["serialNumber"] == "987654321"
    assert result["manufacturer"] == "Continental"


def test_unreadable_character_not_completed_by_guess():
    result = ecu_ai.analyze_transcripts(
        "BOSCH\n0 281 0[?]6 738", "", []
    )
    assert result["primaryNumber"] == ""
    assert result["warnings"]


def test_api_requires_login_csrf_and_optin(tmp_path, monkeypatch):
    monkeypatch.delenv("MAGAZYN_ECU_AI_ENABLED", raising=False)
    app = create_app(str(tmp_path / "inventory.sqlite3"), secure_cookie=False)
    app.state.store.create_user("admin1", "secure-test-password-123", "admin")
    c = TestClient(app)
    payload = {"photo_base64": jpg(), "local_text": "", "barcodes": []}
    assert c.post("/api/ecu-label/analyze", json=payload).status_code == 401
    auth = c.post("/api/auth/login", json={"username": "admin1", "password": "secure-test-password-123"})
    assert auth.status_code == 200
    assert c.post("/api/ecu-label/analyze", json=payload).status_code == 403
    headers = {"X-CSRF-Token": auth.json()["csrf"]}
    assert c.get("/api/ecu-label/status").json() == {"enabled": False}
    assert c.post("/api/ecu-label/analyze", json=payload, headers=headers).status_code == 503
    assert c.get("/api/items").json() == []


def test_api_mocked_model_no_stock_write(tmp_path, monkeypatch):
    monkeypatch.setenv("MAGAZYN_ECU_AI_ENABLED", "1")
    monkeypatch.setattr(
        ecu_ai, "_model_text", lambda image: "Bosch\n0 281 016 738\nHW: 02"
    )
    app = create_app(str(tmp_path / "inventory.sqlite3"), secure_cookie=False)
    app.state.store.create_user("worker1", "second-test-password-456", "user")
    c = TestClient(app)
    auth = c.post("/api/auth/login", json={"username": "worker1", "password": "second-test-password-456"})
    headers = {"X-CSRF-Token": auth.json()["csrf"]}
    result = c.post("/api/ecu-label/analyze", json={
        "photo_base64": jpg(), "local_text": "0 281 016 738", "barcodes": []
    }, headers=headers)
    assert result.status_code == 200, result.text
    assert result.json()["primaryNumber"] == "0281016738"
    assert result.json()["hardware"] == "02"
    assert c.get("/api/items").json() == []
    assert c.get("/api/history").json() == []


def test_invalid_image_rejected_before_model(tmp_path, monkeypatch):
    monkeypatch.setenv("MAGAZYN_ECU_AI_ENABLED", "1")
    app = create_app(str(tmp_path / "inventory.sqlite3"), secure_cookie=False)
    app.state.store.create_user("worker1", "second-test-password-456", "user")
    c = TestClient(app)
    auth = c.post("/api/auth/login", json={"username": "worker1", "password": "second-test-password-456"})
    result = c.post("/api/ecu-label/analyze", json={
        "photo_base64": base64.b64encode(b"<html>fake image</html>" * 9).decode(),
        "local_text": "", "barcodes": []
    }, headers={"X-CSRF-Token": auth.json()["csrf"]})
    assert result.status_code == 422
