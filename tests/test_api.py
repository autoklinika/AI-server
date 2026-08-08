from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from ai_bridge.app import create_app
from ai_bridge.config import Settings


def make_client(tmp_path: Path) -> TestClient:
    app = create_app(
        Settings(
            host="127.0.0.1",
            port=8080,
            database_path=tmp_path / "test.sqlite3",
            ollama_url="http://127.0.0.1:11434",
            ollama_model="qwen3.6:35b",
            analysis_enabled=False,
        )
    )
    return TestClient(app)


def payload() -> dict:
    return {
        "schema_version": 1,
        "source": "ventilation_cm5",
        "device_id": "cm5-main",
        "batch_id": "batch-0001",
        "sequence": 1,
        "timestamp_start": "2026-08-08T00:00:00+02:00",
        "timestamp_end": "2026-08-08T00:00:05+02:00",
        "samples": [
            {
                "timestamp": "2026-08-08T00:00:00+02:00",
                "measurements": {"pm2_5": 11.2, "temperature": 23.4},
                "states": {"fan_1_percent": 35},
            },
            {
                "timestamp": "2026-08-08T00:00:05+02:00",
                "measurements": {"pm2_5": 12.1, "temperature": 23.5},
                "states": {"fan_1_percent": 35},
            },
        ],
    }


def test_health_has_no_control_commands(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        response = client.get("/health")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert body["control_commands_supported"] is False


def test_ingest_ack_and_duplicate_are_idempotent(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        first = client.post("/api/v1/telemetry/batch", json=payload())
        assert first.status_code == 200
        assert first.json()["duplicate"] is False
        assert first.json()["stored_samples"] == 2

        second = client.post("/api/v1/telemetry/batch", json=payload())
        assert second.status_code == 200
        assert second.json()["duplicate"] is True
        assert second.json()["stored_samples"] == 0


def test_history_returns_numeric_measurements(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        client.post("/api/v1/telemetry/batch", json=payload())
        response = client.get(
            "/api/v1/history",
            params={"metric": "pm2_5", "source": "ventilation_cm5"},
        )
        assert response.status_code == 200
        points = response.json()["points"]
        assert [point["value"] for point in points] == [11.2, 12.1]


def test_rejects_timestamp_without_timezone(tmp_path: Path) -> None:
    bad = payload()
    bad["samples"][0]["timestamp"] = "2026-08-08T00:00:00"
    with make_client(tmp_path) as client:
        response = client.post("/api/v1/telemetry/batch", json=bad)
        assert response.status_code == 422


def test_event_is_idempotent(tmp_path: Path) -> None:
    event = {
        "schema_version": 1,
        "source": "ventilation_cm5",
        "device_id": "cm5-main",
        "event_id": "event-0001",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "severity": "critical",
        "event_type": "sensor_bus_failure",
        "payload": {"bus": "sensor"},
    }
    with make_client(tmp_path) as client:
        first = client.post("/api/v1/events", json=event)
        second = client.post("/api/v1/events", json=event)
        assert first.status_code == 200
        assert first.json()["duplicate"] is False
        assert second.json()["duplicate"] is True
