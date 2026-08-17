from __future__ import annotations

import pytest
from pydantic import ValidationError
from sqlalchemy import select

from ai_bridge.settings import Settings
from ai_bridge.storage.models import TelemetrySampleRecord


def test_additive_schedule_and_shadow_fields_reach_raw_archive(client) -> None:
    payload = {
        "schema_version": 1,
        "source_id": "workshop-ventilation-cm5-01",
        "batch_id": "storage-forward-compatible-batch",
        "created_at": "2026-08-17T15:00:05+00:00",
        "samples": [
            {
                "sample_id": "storage-forward-compatible-sample",
                "sequence": 9001,
                "captured_at": "2026-08-17T15:00:00+00:00",
                "metrics": {
                    "mode": "STOP",
                    "setpoints": {
                        "supply_voltage": 0.0,
                        "extract_voltage": 0.0,
                    },
                    "hardware_ready": True,
                    "output_state_known": True,
                    "consecutive_hardware_failures": 0,
                    "active_alarms": [],
                    "sensor_bus": None,
                    "aero_bus": None,
                    "tacho": None,
                    "schedule": {
                        "state": "OCCUPIED_EXPECTED",
                        "rule_id": "weekday-workshop",
                    },
                    "automation": {
                        "execution_mode": "SHADOW",
                        "air_request_pct": 35.0,
                        "proposed_supply_pct": 35.0,
                        "proposed_extract_pct": 40.0,
                        "control_reason": "VOC_REQUEST",
                    },
                },
            }
        ],
    }

    response = client.post("/api/v1/ventilation/telemetry/batches", json=payload)
    assert response.status_code == 200
    assert response.json()["stored"] == 1

    database = client.app.state.database
    with database.session() as session:
        record = session.scalar(
            select(TelemetrySampleRecord).where(
                TelemetrySampleRecord.sample_id
                == "storage-forward-compatible-sample"
            )
        )
        assert record is not None
        assert record.metrics["schedule"]["state"] == "OCCUPIED_EXPECTED"
        assert record.metrics["automation"]["execution_mode"] == "SHADOW"
        assert record.metrics["automation"]["proposed_extract_pct"] == 40.0


def test_stage4_does_not_pretend_nas_backend_exists() -> None:
    with pytest.raises(ValidationError):
        Settings(ventilation_storage_backend="nas")
