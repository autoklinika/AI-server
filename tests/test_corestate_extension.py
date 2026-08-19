from __future__ import annotations

import pytest
from pydantic import ValidationError

from ai_bridge.adapters.ventilation.schemas import VentilationTelemetryBatch


def integrated_sample():
    return {
        "sample_id": "integrated-corestate-1",
        "sequence": 26000,
        "captured_at": "2026-08-18T12:01:03.391220+00:00",
        "metrics": {
            "mode": "STOP",
            "setpoints": {"supply_voltage": 0.0, "extract_voltage": 0.0},
            "hardware_ready": True,
            "output_state_known": True,
            "consecutive_hardware_failures": 0,
            "active_alarms": [
                {
                    "alert_id": 123,
                    "code": "ZIGBEE_DEVICE_DATA_STALE",
                    "source": "zigbee",
                    "severity": "warning",
                    "message": "example",
                    "active_since": "2026-08-18T11:55:00+00:00",
                    "last_error": "example",
                    "occurrences": 1,
                    "acknowledged": False,
                    "acknowledged_at": None,
                    "alert_v2": {
                        "mapped": True,
                        "policy_version": "2",
                        "enabled": True,
                        "weight": 2,
                        "severity": "warning",
                        "reaction": "continue",
                        "scope": "zigbee",
                        "affects_control": False,
                        "hmi_color": "yellow",
                        "category": "service",
                        "correlation_group": "zigbee",
                        "correlation_priority": 10,
                        "title": "Zigbee data stale",
                    },
                }
            ],
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
                "last_cycle_at": "2026-08-18T12:01:03+00:00",
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
                        "status_mask": 771,
                        "reading": {
                            "pm1_0_ug_m3": 4.7,
                            "pm2_5_ug_m3": 5.1,
                            "pm4_0_ug_m3": 5.1,
                            "pm10_0_ug_m3": 5.2,
                            "humidity_percent": 51.86,
                            "temperature_celsius": 23.75,
                            "voc_index": 107.0,
                            "nox_index": 1.0,
                        },
                        "age_seconds": 0,
                        "sensor_errors": 0,
                        "modbus_service_errors": 0,
                        "uptime_seconds": 938,
                        "firmware_version": "0.6",
                        "map_version": 1,
                        "sequence": 933,
                        "last_success_at": "2026-08-18T12:01:03+00:00",
                        "last_error": None,
                        "polls": 468,
                        "successful_polls": 468,
                        "communication_errors": 0,
                        "consecutive_failures": 0,
                        "invalid_measurements": 0,
                        "stale_measurements": 0,
                        "map_version_errors": 0,
                        "sen55_device_status_supported": True,
                        "sen55_device_status_valid": True,
                        "sen55_fan_speed_warning": False,
                        "sen55_fan_cleaning": False,
                        "sen55_gas_sensor_error": False,
                        "sen55_rht_error": False,
                        "sen55_laser_error": False,
                        "sen55_fan_error": False,
                        "sen55_diagnostics_failures": 0,
                    }
                ],
            },
            "aero_bus": {
                "port": "/dev/ttyAMA4",
                "ready": True,
                "online": True,
                "usable": True,
                "telemetry": {"outdoor_temperature_celsius": 21.0},
            },
            "tacho": {
                "chip_path": "/dev/gpiochip0",
                "ready": True,
                "worker_alive": True,
                "supply": {"rpm": 0.0, "valid": False},
                "extract": {"rpm": 0.0, "valid": False},
            },
            "zigbee": {
                "broker_host": "127.0.0.1",
                "connected": True,
                "bridge_online": True,
                "permit_join": False,
                "sensor_list": [
                    {
                        "friendly_name": "temp_zew",
                        "role": "other",
                        "temperature_celsius": 24.32,
                        "humidity_percent": 45.5,
                    }
                ],
            },
            "schedule": {
                "available": True,
                "timezone": "Europe/Warsaw",
                "zones": [],
            },
            "shadow_automation": {
                "enabled": True,
                "actuation_supported": False,
                "status": "TUNING_REQUIRED",
                "zones": [],
            },
            "alert_v2": {
                "runtime_mode": "read_only_mapping",
                "loaded": True,
                "policy_version": "2",
                "sha256": "example-policy-sha",
                "alert_count": 24,
                "source_path": "/etc/workshop-ventilation/alerts-v2.toml",
                "loaded_at": "2026-08-19T08:00:00+00:00",
                "last_attempt_at": "2026-08-19T08:00:00+00:00",
                "last_error": None,
                "control_policy_applied": False,
                "active_weight": 2,
                "hmi_color": "yellow",
                "mapped_active_alerts": 1,
                "disabled_active_alerts": 0,
                "unmapped_active_alerts": 0,
                "service_plane": {
                    "monitor": {"available": True},
                    "correlation": {"available": True},
                    "control_policy_applied": False,
                },
            },
        },
    }


def integrated_batch():
    return {
        "schema_version": 1,
        "source_id": "workshop-ventilation-cm5-01",
        "batch_id": "integrated-corestate-batch-1",
        "created_at": "2026-08-18T12:01:04+00:00",
        "samples": [integrated_sample()],
    }


def test_integrated_cm5_corestate_is_accepted_by_ingest(client):
    response = client.post(
        "/api/v1/ventilation/telemetry/batches",
        json=integrated_batch(),
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["received"] == 1
    assert payload["stored"] == 1
    assert payload["rejected"] == 0


def test_integrated_corestate_extensions_survive_schema_serialization():
    batch = VentilationTelemetryBatch.model_validate(integrated_batch())
    metrics = batch.model_dump(mode="json")["samples"][0]["metrics"]

    assert metrics["sensor_bus"]["nodes"][0]["sen55_device_status_valid"] is True
    assert metrics["active_alarms"][0]["alert_id"] == 123
    assert metrics["active_alarms"][0]["source"] == "zigbee"
    assert metrics["active_alarms"][0]["alert_v2"]["mapped"] is True
    assert metrics["active_alarms"][0]["alert_v2"]["affects_control"] is False
    assert metrics["aero_bus"]["online"] is True
    assert metrics["tacho"]["chip_path"] == "/dev/gpiochip0"
    assert metrics["zigbee"]["sensor_list"][0]["friendly_name"] == "temp_zew"
    assert metrics["schedule"]["available"] is True
    assert metrics["shadow_automation"]["actuation_supported"] is False
    assert metrics["alert_v2"]["runtime_mode"] == "read_only_mapping"
    assert metrics["alert_v2"]["control_policy_applied"] is False


def test_unrelated_corestate_extension_remains_rejected():
    batch = integrated_batch()
    batch["samples"][0]["metrics"]["unexpected_control_plane"] = {"enabled": True}

    with pytest.raises(ValidationError):
        VentilationTelemetryBatch.model_validate(batch)


def test_unrelated_alarm_extension_remains_rejected():
    batch = integrated_batch()
    batch["samples"][0]["metrics"]["active_alarms"][0]["unexpected_field"] = True

    with pytest.raises(ValidationError):
        VentilationTelemetryBatch.model_validate(batch)
