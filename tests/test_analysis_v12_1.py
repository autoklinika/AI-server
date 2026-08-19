from __future__ import annotations

import pytest

from ai_bridge.adapters.ventilation.analysis_v12_1 import (
    PROMPT_VERSION,
    EnvironmentalDecisionV121,
    build_environment_fact_catalog,
    render_result,
    resolve_final_decision,
    validate_environmental_decision,
)


def _metric(first: float, last: float, *, missing: int = 0) -> dict:
    return {
        "count": 180 - missing,
        "missing": missing,
        "mean": (first + last) / 2,
        "min": min(first, last),
        "max": max(first, last),
        "first": first,
        "last": last,
        "delta": last - first,
        "slope_per_minute": (last - first) / 15,
    }


def _packet() -> dict:
    node = {
        "samples_present": 180,
        "online_ratio": 1.0,
        "measurement_valid_ratio": 1.0,
        "measurement_stale_ratio": 0.0,
        "sensor_present_ratio": 1.0,
        "diagnostic_counter_deltas": {
            "sensor_errors": 0,
            "modbus_service_errors": 0,
            "communication_errors": 0,
            "invalid_measurements": 0,
            "stale_measurements": 0,
            "map_version_errors": 0,
        },
        "consecutive_failures_max": 0,
        "latest_error": None,
        "readings": {
            "pm2_5_ug_m3": _metric(4.0, 4.0),
            "pm10_0_ug_m3": _metric(5.0, 5.0),
            "voc_index": _metric(20.0, 20.0),
        },
    }
    return {
        "schema_version": 1,
        "source_id": "benchmark-ai-server",
        "window": {
            "start": "2026-08-19T10:00:00+02:00",
            "end": "2026-08-19T10:15:00+02:00",
            "sample_count": 180,
            "capture_span_seconds": 897.0,
        },
        "analysis_context": {
            "historical_baseline_available": False,
            "expected_operating_state_known": False,
        },
        "measurement_capabilities": {
            "present_in_packet": ["pm2_5_ug_m3", "pm10_0_ug_m3", "voc_index"],
            "not_provided_by_system": ["co2", "airflow"],
            "excluded_from_current_analysis_packet": ["fan_rpm", "tacho"],
        },
        "controller": {
            "latest_mode": "MANUAL",
            "mode_counts": {"MANUAL": 180},
            "setpoints": {
                "supply_voltage": {
                    "mean": 6.0,
                    "min": 6.0,
                    "max": 6.0,
                    "first": 6.0,
                    "last": 6.0,
                    "delta": 0.0,
                },
                "extract_voltage": {
                    "mean": 7.0,
                    "min": 7.0,
                    "max": 7.0,
                    "first": 7.0,
                    "last": 7.0,
                    "delta": 0.0,
                },
            },
            "hardware_ready_ratio": 1.0,
            "output_state_known_ratio": 1.0,
            "consecutive_hardware_failures_max": 0,
            "active_alarm_sample_count": 0,
            "active_alarm_codes": [],
        },
        "sensor_bus": {
            "ready_ratio": 1.0,
            "worker_alive_ratio": 1.0,
            "worker_restarts_max": 0,
            "latest_error": None,
            "nodes": {"1": node, "2": dict(node)},
        },
    }


def _env(attention: bool, facts: list[str] | None = None) -> EnvironmentalDecisionV121:
    return EnvironmentalDecisionV121(
        environmental_attention=attention,
        selected_fact_ids=facts or [],
    )


def test_v12_1_model_catalog_excludes_technical_and_quality_facts() -> None:
    packet = _packet()
    ids = {fact["id"] for fact in build_environment_fact_catalog(packet)}
    assert PROMPT_VERSION == "ventilation-v12.1-grounded-decision"
    assert "controller:alarms" not in ids
    assert "sensor_bus:health" not in ids
    assert "node:1:health" not in ids
    reading = next(
        fact for fact in build_environment_fact_catalog(packet)
        if fact["id"] == "node:1:reading:voc_index"
    )
    assert "missing" not in reading
    assert "count" not in reading


def test_v12_1_stable_environment_resolves_no_anomaly() -> None:
    decision = resolve_final_decision(_packet(), _env(False))
    assert decision.status == "no_anomaly_detected"
    assert decision.reason_codes == ["no_significant_issue"]
    assert decision.recommendation_code == "none"


def test_v12_1_environmental_attention_resolves_attention() -> None:
    packet = _packet()
    packet["sensor_bus"]["nodes"]["1"]["readings"]["pm10_0_ug_m3"] = _metric(4.9, 163.4)
    decision = resolve_final_decision(
        packet,
        _env(True, ["node:1:reading:pm10_0_ug_m3"]),
    )
    assert decision.status == "attention"
    assert decision.reason_codes == ["environmental_change"]
    assert decision.recommendation_code == "observe_next_windows"


def test_v12_1_partial_missing_forces_attention_even_if_qwen_says_false() -> None:
    packet = _packet()
    packet["sensor_bus"]["nodes"]["1"]["readings"]["voc_index"] = _metric(
        95.0, 96.0, missing=10
    )
    decision = resolve_final_decision(packet, _env(False))
    assert decision.status == "attention"
    assert "data_quality_issue" in decision.reason_codes
    assert decision.recommendation_code == "none"
    rendered = render_result(packet, _env(False))
    assert "missing=10" in rendered.data_quality_pl


def test_v12_1_active_alarm_forces_anomaly_without_model_alarm_decision() -> None:
    packet = _packet()
    packet["controller"]["active_alarm_sample_count"] = 178
    packet["controller"]["active_alarm_codes"] = ["AERO_BUS_UNAVAILABLE"]
    decision = resolve_final_decision(packet, _env(False))
    assert decision.status == "anomaly"
    assert "technical_alarm" in decision.reason_codes
    assert decision.recommendation_code == "diagnose_active_alarm"
    assert "alarm:AERO_BUS_UNAVAILABLE" in decision.selected_fact_ids


def test_v12_1_hard_sensor_bus_failure_forces_anomaly() -> None:
    packet = _packet()
    packet["sensor_bus"]["worker_alive_ratio"] = 0.0
    decision = resolve_final_decision(packet, _env(False))
    assert decision.status == "anomaly"
    assert "technical_degradation" in decision.reason_codes
    assert "sensor_bus:health" in decision.selected_fact_ids


def test_v12_1_rejects_fact_id_outside_environment_catalog() -> None:
    packet = _packet()
    with pytest.raises(ValueError):
        validate_environmental_decision(
            packet,
            _env(True, ["alarm:NOT_ALLOWED"]),
        )
