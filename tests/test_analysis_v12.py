from __future__ import annotations

import pytest

from ai_bridge.adapters.ventilation.analysis_v12 import (
    PROMPT_VERSION,
    VentilationDecisionV12,
    build_decision_packet_from_compact,
    build_fact_catalog,
    render_data_quality,
    render_result,
    validate_decision,
)


def _metric(*, first: float, last: float, missing: int = 0, count: int = 180) -> dict:
    return {
        "count": count,
        "missing": missing,
        "mean": (first + last) / 2,
        "min": min(first, last),
        "max": max(first, last),
        "first": first,
        "last": last,
        "delta": last - first,
        "slope_per_minute": (last - first) / 15,
    }


def _packet(*, alarms: list[str] | None = None, missing_voc: int = 0) -> dict:
    alarms = alarms or []
    return {
        "schema_version": 1,
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
            "present_in_packet": ["pm2_5_ug_m3", "voc_index"],
            "not_provided_by_system": ["co2", "airflow"],
            "excluded_from_current_analysis_packet": ["fan_rpm", "tacho"],
        },
        "controller": {
            "latest_mode": "MANUAL",
            "mode_counts": {"MANUAL": 180},
            "setpoints": {
                "supply_voltage": {
                    "mean": 3.75,
                    "min": 2.5,
                    "max": 5.0,
                    "first": 5.0,
                    "last": 2.5,
                    "delta": -2.5,
                },
                "extract_voltage": {
                    "mean": 4.0,
                    "min": 2.0,
                    "max": 6.0,
                    "first": 6.0,
                    "last": 2.0,
                    "delta": -4.0,
                },
            },
            "hardware_ready_ratio": 1.0,
            "output_state_known_ratio": 1.0,
            "consecutive_hardware_failures_max": 0,
            "active_alarm_sample_count": 20 if alarms else 0,
            "active_alarm_codes": alarms,
        },
        "sensor_bus": {
            "ready_ratio": 1.0,
            "worker_alive_ratio": 1.0,
            "worker_restarts_max": 0,
            "latest_error": None,
            "nodes": {
                "1": {
                    "samples_present": 180,
                    "online_ratio": 1.0,
                    "measurement_valid_ratio": 1.0,
                    "measurement_stale_ratio": 0.0,
                    "sensor_present_ratio": 1.0,
                    "diagnostic_counter_deltas": {},
                    "consecutive_failures_max": 0,
                    "latest_error": None,
                    "readings": {
                        "pm2_5_ug_m3": _metric(first=84.5, last=3.9),
                        "voc_index": _metric(
                            first=32.0,
                            last=79.0,
                            missing=missing_voc,
                            count=180 - missing_voc,
                        ),
                    },
                },
                "2": {
                    "samples_present": 180,
                    "online_ratio": 1.0,
                    "measurement_valid_ratio": 1.0,
                    "measurement_stale_ratio": 0.0,
                    "sensor_present_ratio": 1.0,
                    "diagnostic_counter_deltas": {},
                    "consecutive_failures_max": 0,
                    "latest_error": None,
                    "readings": {
                        "pm2_5_ug_m3": _metric(first=78.6, last=3.7),
                        "voc_index": _metric(first=43.0, last=94.0),
                    },
                },
            },
        },
    }


def test_v12_profile_is_structured_decision() -> None:
    assert PROMPT_VERSION == "ventilation-v12-structured-decision"
    model_packet = build_decision_packet_from_compact(_packet())
    assert model_packet["facts"]
    assert all("id" in fact and "kind" in fact for fact in model_packet["facts"])


def test_v12_renderer_preserves_supply_extract_identity() -> None:
    packet = _packet()
    decision = VentilationDecisionV12(
        status="attention",
        reason_codes=["environmental_change"],
        selected_fact_ids=[
            "controller:setpoint:supply_voltage",
            "controller:setpoint:extract_voltage",
            "node:1:reading:voc_index",
            "node:2:reading:voc_index",
        ],
        recommendation_code="observe_next_windows",
    )
    result = render_result(packet, decision)

    assert "supply_voltage: first=5 V, last=2,5 V, delta=-2,5 V" in result.analysis_pl
    assert "extract_voltage: first=6 V, last=2 V, delta=-4 V" in result.analysis_pl
    assert "Węzeł 1, VOC Index: first=32, last=79" in result.analysis_pl
    assert "Węzeł 2, VOC Index: first=43, last=94" in result.analysis_pl
    assert "80" not in result.analysis_pl


def test_v12_data_quality_is_deterministic_for_partial_missing() -> None:
    quality = render_data_quality(_packet(missing_voc=10))
    assert "węzeł 1, VOC Index: missing=10" in quality
    assert "Wszystkie kanały pomiarowe obecne w pakiecie mają missing=0" not in quality
    assert "TACHO/RPM są wyłączone" in quality
    assert "CO2 i przepływ nie są dostarczane" in quality


def test_v12_active_alarm_requires_anomaly_and_alarm_fact() -> None:
    packet = _packet(alarms=["AERO_BUS_UNAVAILABLE"])
    invalid = VentilationDecisionV12(
        status="attention",
        reason_codes=["environmental_change"],
        selected_fact_ids=["node:1:reading:voc_index"],
        recommendation_code="observe_next_windows",
    )
    with pytest.raises(ValueError, match="active alarm requires"):
        validate_decision(packet, invalid)

    valid = VentilationDecisionV12(
        status="anomaly",
        reason_codes=["technical_alarm"],
        selected_fact_ids=["alarm:AERO_BUS_UNAVAILABLE"],
        recommendation_code="diagnose_active_alarm",
    )
    result = render_result(packet, valid)
    assert "Aktywny alarm: AERO_BUS_UNAVAILABLE" in result.analysis_pl
    assert "AERO_BUS_UNAVAILABLE" in result.operator_recommendation_pl
    assert "magistrali czujników" not in result.operator_recommendation_pl


def test_v12_rejects_unknown_fact_id() -> None:
    packet = _packet()
    decision = VentilationDecisionV12(
        status="attention",
        reason_codes=["environmental_change"],
        selected_fact_ids=["node:99:reading:voc_index"],
        recommendation_code="observe_next_windows",
    )
    with pytest.raises(ValueError, match="unknown fact IDs"):
        validate_decision(packet, decision)


def test_v12_fact_ids_are_unique() -> None:
    ids = [fact["id"] for fact in build_fact_catalog(_packet())]
    assert len(ids) == len(set(ids))
