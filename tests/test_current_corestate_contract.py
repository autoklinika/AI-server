from __future__ import annotations

from ai_bridge.adapters.ventilation.schemas import VentilationTelemetryBatch


def current_core_state_metrics() -> dict:
    node = {
        "slave_address": 1,
        "online": True,
        "usable": True,
        "measurement_valid": True,
        "measurement_stale": False,
        "sensor_present": True,
        "availability_mask": 255,
        "status_mask": 0x0303,
        "reading": {
            "pm1_0_ug_m3": 3.1,
            "pm2_5_ug_m3": 4.2,
            "pm4_0_ug_m3": 5.3,
            "pm10_0_ug_m3": 6.4,
            "humidity_percent": 46.0,
            "temperature_celsius": 22.5,
            "voc_index": 89.0,
            "nox_index": 1.0,
        },
        "age_seconds": 0,
        "sensor_errors": 0,
        "modbus_service_errors": 0,
        "uptime_seconds": 1234,
        "firmware_version": "0.6.0-stage1-sen55-status",
        "map_version": 1,
        "sequence": 101,
        "last_success_at": "2026-08-17T13:50:00+00:00",
        "last_error": None,
        "polls": 1000,
        "successful_polls": 1000,
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
    node2 = {**node, "slave_address": 2, "sequence": 102}

    return {
        "mode": "STOP",
        "setpoints": {"supply_voltage": 0.0, "extract_voltage": 0.0},
        "hardware_ready": True,
        "output_state_known": True,
        "consecutive_hardware_failures": 0,
        "active_alarms": [
            {
                "alert_id": 12,
                "code": "SEN55_FAN_ERROR",
                "source": "sensor:1",
                "severity": "warning",
                "message": "SEN55 internal fan error",
                "active_since": "2026-08-17T13:46:44+00:00",
                "last_error": "device status bit 4",
                "occurrences": 1,
                "acknowledged": True,
                "acknowledged_at": "2026-08-17T13:47:57+00:00",
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
            "last_cycle_at": "2026-08-17T13:50:00+00:00",
            "last_error": None,
            "nodes": [node, node2],
        },
        "aero_bus": {
            "port": "/dev/ttyAMA1",
            "baudrate": 9600,
            "slave_address": 1,
            "register_addresses": [100, 101, 102],
            "inter_register_delay_seconds": 0.02,
            "poll_interval_seconds": 1.0,
            "ready": True,
            "worker_alive": True,
            "worker_restarts": 0,
            "online": True,
            "usable": True,
            "telemetry": {
                "humidity_percent": 45.0,
                "supply_temperature_celsius": 21.0,
                "extract_temperature_celsius": 23.0,
                "outdoor_temperature_celsius": 18.0,
                "fan_1_percent": 0,
                "fan_2_percent": 0,
            },
            "control_busy": False,
            "last_control_result": None,
            "last_success_at": "2026-08-17T13:50:00+00:00",
            "last_cycle_at": "2026-08-17T13:50:00+00:00",
            "last_error": None,
            "polls": 1000,
            "successful_polls": 1000,
            "communication_errors": 0,
            "consecutive_failures": 0,
            "invalid_samples": 0,
        },
        "tacho": {
            "chip_path": "/dev/gpiochip0",
            "ready": True,
            "worker_alive": True,
            "last_error": None,
            "supply": {
                "line_name": "GPIO17",
                "line_offset": 17,
                "frequency_hz": 70.5,
                "rpm": 1410.0,
                "sample_count": 6,
                "age_seconds": 0.01,
                "valid": True,
            },
            "extract": {
                "line_name": "GPIO27",
                "line_offset": 27,
                "frequency_hz": 0.0,
                "rpm": 0.0,
                "sample_count": 0,
                "age_seconds": 0.3,
                "valid": False,
            },
        },
        # Stage 1 history must not require an AI deployment for every additive
        # CoreState field. These represent the future schedule/SHADOW envelope.
        "schedule": {"state": "OCCUPIED_EXPECTED"},
        "automation": {
            "execution_mode": "SHADOW",
            "proposed_supply_pct": 35.0,
            "proposed_extract_pct": 40.0,
            "control_reason": "VOC_REQUEST",
        },
    }


def test_current_cm5_core_state_and_additive_fields_are_preserved() -> None:
    payload = {
        "schema_version": 1,
        "source_id": "workshop-ventilation-cm5-01",
        "batch_id": "current-core-state-batch",
        "created_at": "2026-08-17T13:50:01+00:00",
        "samples": [
            {
                "sample_id": "current-core-state-sample",
                "sequence": 1001,
                "captured_at": "2026-08-17T13:50:00+00:00",
                "metrics": current_core_state_metrics(),
            }
        ],
    }

    parsed = VentilationTelemetryBatch.model_validate(payload)
    dumped = parsed.model_dump(mode="json")
    metrics = dumped["samples"][0]["metrics"]

    assert metrics["sensor_bus"]["nodes"][0]["sen55_device_status_valid"] is True
    assert metrics["aero_bus"]["online"] is True
    assert metrics["tacho"]["supply"]["rpm"] == 1410.0
    assert metrics["active_alarms"][0]["alert_id"] == 12
    assert metrics["active_alarms"][0]["acknowledged"] is True
    assert metrics["schedule"]["state"] == "OCCUPIED_EXPECTED"
    assert metrics["automation"]["execution_mode"] == "SHADOW"
