from __future__ import annotations

from copy import deepcopy


def sample(sample_id: str, sequence: int):
    return {
        "sample_id": sample_id,
        "sequence": sequence,
        "captured_at": "2026-08-08T13:29:55.250+02:00",
        "metrics": {
            "mode": "MANUAL",
            "setpoints": {"supply_voltage": 6.0, "extract_voltage": 5.5},
            "hardware_ready": True,
            "output_state_known": True,
            "consecutive_hardware_failures": 0,
            "active_alarms": [],
            "sensor_bus": {
                "port": "/dev/ttyAMA0",
                "baudrate": 19200,
                "addresses": [1, 2],
                "ready": True,
                "worker_alive": True,
                "worker_restarts": 0,
                "expected_map_version": 1,
                "inter_node_delay_seconds": 0.01,
                "poll_interval_seconds": 1.0,
                "last_cycle_at": "2026-08-08T11:29:55+00:00",
                "last_error": None,
                "nodes": [
                    {
                        "slave_address": 1,
                        "online": True,
                        "usable": True,
                        "measurement_valid": True,
                        "measurement_stale": False,
                        "sensor_present": True,
                        "availability_mask": 255,
                        "status_mask": 3,
                        "reading": {
                            "pm1_0_ug_m3": 4.2,
                            "pm2_5_ug_m3": 6.1,
                            "pm4_0_ug_m3": 7.3,
                            "pm10_0_ug_m3": 8.0,
                            "humidity_percent": 48.5,
                            "temperature_celsius": 22.7,
                            "voc_index": 97.0,
                            "nox_index": 1.0,
                        },
                        "age_seconds": 0,
                        "sensor_errors": 0,
                        "modbus_service_errors": 0,
                        "uptime_seconds": 123456,
                        "firmware_version": "0.3",
                        "map_version": 1,
                        "sequence": 12345,
                        "last_success_at": "2026-08-08T11:29:55+00:00",
                        "last_error": None,
                        "polls": 45678,
                        "successful_polls": 45678,
                        "communication_errors": 0,
                        "consecutive_failures": 0,
                        "invalid_measurements": 0,
                        "stale_measurements": 0,
                        "map_version_errors": 0,
                    },
                    {
                        "slave_address": 2,
                        "online": True,
                        "usable": True,
                        "measurement_valid": True,
                        "measurement_stale": False,
                        "sensor_present": True,
                        "availability_mask": 255,
                        "status_mask": 3,
                        "reading": {
                            "pm1_0_ug_m3": 5.0,
                            "pm2_5_ug_m3": 7.2,
                            "pm4_0_ug_m3": 8.1,
                            "pm10_0_ug_m3": 9.0,
                            "humidity_percent": 47.8,
                            "temperature_celsius": 22.4,
                            "voc_index": 91.0,
                            "nox_index": 1.0,
                        },
                        "age_seconds": 0,
                        "sensor_errors": 0,
                        "modbus_service_errors": 0,
                        "uptime_seconds": 123450,
                        "firmware_version": "0.3",
                        "map_version": 1,
                        "sequence": 12342,
                        "last_success_at": "2026-08-08T11:29:55+00:00",
                        "last_error": None,
                        "polls": 45678,
                        "successful_polls": 45678,
                        "communication_errors": 0,
                        "consecutive_failures": 0,
                        "invalid_measurements": 0,
                        "stale_measurements": 0,
                        "map_version_errors": 0,
                    },
                ],
            },
        },
    }


def batch(batch_id="batch-1", samples=None):
    return {
        "schema_version": 1,
        "source_id": "workshop-ventilation-cm5-01",
        "batch_id": batch_id,
        "created_at": "2026-08-08T13:30:00+02:00",
        "samples": samples or [sample("sample-1", 1), sample("sample-2", 2)],
    }


def test_health_reports_database_and_no_control_commands(client):
    response = client.get("/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["components"]["database"] == "ok"
    assert payload["control_commands_supported"] is False


def test_storage_status_is_read_only_and_non_secret(client):
    response = client.get("/api/v1/ventilation/storage/status")
    assert response.status_code == 200
    payload = response.json()
    assert payload == {
        "status_schema_version": 1,
        "backend": "sql",
        "location_label": "AI Server",
        "available": True,
        "switch_supported": False,
        "configuration_write_supported": False,
        "control_commands_supported": False,
    }
    assert "database_url" not in payload


def test_ingest_and_retransmit_is_idempotent(client):
    payload = batch()
    first = client.post("/api/v1/ventilation/telemetry/batches", json=payload)
    assert first.status_code == 200
    assert first.json()["stored"] == 2
    assert first.json()["duplicates"] == 0

    second = client.post("/api/v1/ventilation/telemetry/batches", json=payload)
    assert second.status_code == 200
    assert second.json()["stored"] == 0
    assert second.json()["duplicates"] == 2


def test_overlapping_batch_stores_only_new_samples(client):
    first = client.post(
        "/api/v1/ventilation/telemetry/batches",
        json=batch("batch-a", [sample("sample-1", 1), sample("sample-2", 2)]),
    )
    assert first.status_code == 200

    second = client.post(
        "/api/v1/ventilation/telemetry/batches",
        json=batch("batch-b", [sample("sample-2", 2), sample("sample-3", 3)]),
    )
    assert second.status_code == 200
    assert second.json()["stored"] == 1
    assert second.json()["duplicates"] == 1


def test_reusing_batch_id_with_different_payload_is_conflict(client):
    original = batch()
    assert client.post("/api/v1/ventilation/telemetry/batches", json=original).status_code == 200

    changed = deepcopy(original)
    changed["samples"][0]["metrics"]["setpoints"]["supply_voltage"] = 7.0
    response = client.post("/api/v1/ventilation/telemetry/batches", json=changed)
    assert response.status_code == 409
    assert response.json()["error"] == "batch_identity_conflict"


def test_unsupported_schema_version_is_400(client):
    payload = batch()
    payload["schema_version"] = 2
    response = client.post("/api/v1/ventilation/telemetry/batches", json=payload)
    assert response.status_code == 400
    assert response.json()["supported_versions"] == [1]


def test_naive_timestamp_is_rejected(client):
    payload = batch()
    payload["samples"][0]["captured_at"] = "2026-08-08T13:29:55"
    response = client.post("/api/v1/ventilation/telemetry/batches", json=payload)
    assert response.status_code == 422


def test_additive_domain_metrics_field_is_accepted(client):
    payload = batch("batch-additive", [sample("sample-additive", 1)])
    payload["samples"][0]["metrics"]["future_additive_field"] = {
        "value": 1234,
        "reason": "forward-compatible domain telemetry",
    }
    response = client.post("/api/v1/ventilation/telemetry/batches", json=payload)
    assert response.status_code == 200
    assert response.json()["stored"] == 1


def test_transport_envelope_remains_strict(client):
    payload = batch()
    payload["unexpected_transport_field"] = "must-not-be-accepted"
    response = client.post("/api/v1/ventilation/telemetry/batches", json=payload)
    assert response.status_code == 422


def test_openapi_exposes_no_control_endpoint(client):
    paths = client.get("/openapi.json").json()["paths"]
    assert "/api/v1/ventilation/telemetry/batches" in paths
    assert "/api/v1/ventilation/storage/status" in paths
    forbidden = ("control", "command", "set-speed", "actuator")
    assert all(not any(word in path.lower() for word in forbidden) for path in paths)


def test_duplicate_sample_id_inside_batch_is_rejected(client):
    payload = batch(
        "batch-duplicate-sample",
        [sample("same-sample", 1), sample("same-sample", 2)],
    )
    response = client.post("/api/v1/ventilation/telemetry/batches", json=payload)
    assert response.status_code == 422


def test_sensor_bus_null_is_accepted_as_real_core_state_shape(client):
    payload = batch("batch-no-sensor-bus", [sample("sample-no-bus", 1)])
    payload["samples"][0]["metrics"]["sensor_bus"] = None
    response = client.post("/api/v1/ventilation/telemetry/batches", json=payload)
    assert response.status_code == 200
    assert response.json()["stored"] == 1


def test_oversized_content_length_is_rejected_before_ingestion(client):
    response = client.post(
        "/api/v1/ventilation/telemetry/batches",
        content=b"{}",
        headers={
            "content-type": "application/json",
            "content-length": str(1_048_577),
        },
    )
    assert response.status_code == 413
    assert response.json()["error"] == "request_too_large"
