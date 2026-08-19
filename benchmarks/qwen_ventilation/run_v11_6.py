from __future__ import annotations

"""Semantic benchmark entrypoint for ventilation prompt v11.6.

This wrapper keeps all v11.5 scenarios and adds regressions discovered while
validating archived real telemetry windows.
"""

from copy import deepcopy
from typing import Any

import run_v11_5 as previous

from ai_bridge.adapters.ventilation.analysis_profile_v11_6 import (
    ANALYSIS_THINK,
    PROMPT_VERSION,
    SYSTEM_PROMPT,
)


engine = previous.base
_legacy_load_scenarios = previous.load_scenarios_v11_5


def load_scenarios_v11_6() -> list[dict[str, Any]]:
    scenarios = deepcopy(_legacy_load_scenarios())

    scenarios.extend(
        [
            {
                "id": "pm_fall_real_grounding_regression",
                "description": (
                    "Real-window regression: model must use only current first/last values, "
                    "must not invent correlation between setpoints and PM, must not derive a "
                    "14-minute window from capture_span_seconds, and must not turn unknown "
                    "operator intent into an action recommendation."
                ),
                "allowed_status": ["attention"],
                "overrides": {
                    "window": {
                        "start": "2026-08-13T16:30:00+02:00",
                        "end": "2026-08-13T16:45:00+02:00",
                        "sample_count": 180,
                        "capture_span_seconds": 896.874,
                    },
                    "controller": {
                        "latest_mode": "MANUAL",
                        "mode_counts": {"MANUAL": 180},
                        "setpoints": {
                            "supply_voltage": {
                                "mean": 3.1944,
                                "min": 2.5,
                                "max": 5.0,
                                "first": 5.0,
                                "last": 2.5,
                                "delta": -2.5,
                            },
                            "extract_voltage": {
                                "mean": 3.1111,
                                "min": 2.0,
                                "max": 6.0,
                                "first": 6.0,
                                "last": 2.0,
                                "delta": -4.0,
                            },
                        },
                    },
                    "sensor_bus": {
                        "nodes": {
                            "1": {
                                "readings": {
                                    "pm2_5_ug_m3": {
                                        "count": 180,
                                        "missing": 0,
                                        "mean": 27.7772,
                                        "min": 3.9,
                                        "max": 84.5,
                                        "first": 84.5,
                                        "last": 3.9,
                                        "delta": -80.6,
                                        "slope_per_minute": -5.2171,
                                    },
                                    "pm10_0_ug_m3": {
                                        "count": 180,
                                        "missing": 0,
                                        "mean": 51.05,
                                        "min": 5.8,
                                        "max": 159.2,
                                        "first": 159.2,
                                        "last": 5.8,
                                        "delta": -153.4,
                                        "slope_per_minute": -9.8933,
                                    },
                                    "voc_index": {
                                        "count": 180,
                                        "missing": 0,
                                        "mean": 59.8667,
                                        "min": 24.0,
                                        "max": 109.0,
                                        "first": 32.0,
                                        "last": 79.0,
                                        "delta": 47.0,
                                        "slope_per_minute": 1.3518,
                                    },
                                }
                            },
                            "2": {
                                "readings": {
                                    "pm2_5_ug_m3": {
                                        "count": 180,
                                        "missing": 0,
                                        "mean": 25.5733,
                                        "min": 3.4,
                                        "max": 78.6,
                                        "first": 78.6,
                                        "last": 3.7,
                                        "delta": -74.9,
                                        "slope_per_minute": -4.6939,
                                    },
                                    "pm10_0_ug_m3": {
                                        "count": 180,
                                        "missing": 0,
                                        "mean": 47.5028,
                                        "min": 5.3,
                                        "max": 149.8,
                                        "first": 149.8,
                                        "last": 5.7,
                                        "delta": -144.1,
                                        "slope_per_minute": -9.0296,
                                    },
                                    "voc_index": {
                                        "count": 180,
                                        "missing": 0,
                                        "mean": 73.6222,
                                        "min": 31.0,
                                        "max": 126.0,
                                        "first": 43.0,
                                        "last": 94.0,
                                        "delta": 51.0,
                                        "slope_per_minute": 2.0598,
                                    },
                                }
                            },
                        }
                    },
                },
                "must_match": [
                    {
                        "name": "uses_current_node1_voc_endpoints",
                        "field": "analysis_pl",
                        "mode": "all",
                        "patterns": [
                            r"VOC",
                            r"32(?:[.,]0)?.{0,60}79(?:[.,]0)?",
                        ],
                    },
                    {
                        "name": "uses_current_node2_voc_endpoints",
                        "field": "analysis_pl",
                        "mode": "all",
                        "patterns": [
                            r"43(?:[.,]0)?.{0,60}94(?:[.,]0)?",
                        ],
                    },
                ],
                "must_not_match": [
                    {
                        "name": "does_not_leak_previous_window_voc_values",
                        "field": "analysis_pl",
                        "pattern": r"VOC Index.{0,120}80(?:[.,]0)?.{0,30}32(?:[.,]0)?|delta\s*-48",
                    },
                    {
                        "name": "does_not_claim_uncomputed_correlation",
                        "field": "analysis_pl",
                        "pattern": r"korelacj|skorelow|zależnoś|\bwpływ\b|spowod|skutkow|reakcj[aię] na",
                    },
                    {
                        "name": "does_not_call_window_14_minutes",
                        "field": "analysis_pl",
                        "pattern": r"\b14\s*(?:minut|min\b)",
                    },
                    {
                        "name": "does_not_turn_unknown_intent_into_recommendation",
                        "field": "operator_recommendation_pl",
                        "pattern": r"zweryfik|sprawdź|sprawdzić|upewni|czy .*zamierzon|zamiar operatora",
                    },
                    {
                        "name": "does_not_recommend_searching_unknown_source",
                        "field": "operator_recommendation_pl",
                        "pattern": r"sprawdź przyczyn|sprawdzić przyczyn|szukaj przyczyn|szukać przyczyn|lokaliz.*źród",
                    },
                ],
            },
            {
                "id": "aero_alarm_scope_and_excluded_rpm",
                "description": (
                    "AERO_BUS_UNAVAILABLE must justify anomaly without being reinterpreted as "
                    "SENSOR BUS/sensor-bus failure, and excluded TACHO/RPM must not be described "
                    "as absent from the system."
                ),
                "allowed_status": ["anomaly"],
                "overrides": {
                    "controller": {
                        "latest_mode": "STOP",
                        "mode_counts": {"STOP": 180},
                        "setpoints": {
                            "supply_voltage": {
                                "mean": 0.0,
                                "min": 0.0,
                                "max": 0.0,
                                "first": 0.0,
                                "last": 0.0,
                                "delta": 0.0,
                            },
                            "extract_voltage": {
                                "mean": 0.0,
                                "min": 0.0,
                                "max": 0.0,
                                "first": 0.0,
                                "last": 0.0,
                                "delta": 0.0,
                            },
                        },
                        "active_alarm_sample_count": 178,
                        "active_alarm_codes": ["AERO_BUS_UNAVAILABLE"],
                    },
                    "sensor_bus": {
                        "ready_ratio": 1.0,
                        "worker_alive_ratio": 1.0,
                        "worker_restarts_max": 0,
                        "latest_error": None,
                    },
                },
                "must_match": [
                    {
                        "name": "names_aero_alarm_in_analysis",
                        "field": "analysis_pl",
                        "patterns": ["AERO_BUS_UNAVAILABLE"],
                    }
                ],
                "must_not_match": [
                    {
                        "name": "does_not_claim_rpm_or_tacho_absent",
                        "field": "all",
                        "pattern": r"brak danych.{0,50}(?:RPM|TACHO)|(?:RPM|TACHO).{0,50}brak danych|system.{0,50}(?:nie ma|nie posiada).{0,30}(?:RPM|TACHO)",
                    },
                    {
                        "name": "does_not_map_aero_alarm_to_sensor_bus",
                        "field": "operator_recommendation_pl",
                        "pattern": r"AERO_BUS_UNAVAILABLE.{0,140}(?:SENSOR BUS|magistral.{0,30}czujnik|czujnik.{0,30}magistral)",
                    },
                    {
                        "name": "does_not_invent_aero_root_cause",
                        "field": "operator_recommendation_pl",
                        "pattern": r"AERO_BUS_UNAVAILABLE.{0,100}(?:wskazuje|oznacza).{0,80}(?:przyczyn|uszkodz|awarię czujnik|problem z czujnik)",
                    },
                ],
            },
        ]
    )

    return scenarios


engine.PROMPT_VERSION = PROMPT_VERSION
engine.SYSTEM_PROMPT = SYSTEM_PROMPT
engine.ANALYSIS_THINK = ANALYSIS_THINK
engine.base_packet = previous.base_packet_v11_5
engine.load_scenarios = load_scenarios_v11_6


if __name__ == "__main__":
    raise SystemExit(engine.main())
