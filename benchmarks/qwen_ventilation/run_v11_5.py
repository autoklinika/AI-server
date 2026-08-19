from __future__ import annotations

"""Semantic benchmark entrypoint for ventilation prompt v11.5.

The established benchmark engine remains in run.py. This wrapper aligns the
synthetic packet with the v11.5 production compact-packet contract and adds
regressions discovered during archived real-window validation.
"""

from copy import deepcopy
from typing import Any

import run as base


_legacy_base_packet = base.base_packet
_legacy_load_scenarios = base.load_scenarios


def _add_endpoints(metric: dict[str, Any]) -> None:
    if "delta" not in metric or "min" not in metric or "max" not in metric:
        return
    if "first" in metric and "last" in metric:
        return

    delta = metric.get("delta")
    minimum = metric.get("min")
    maximum = metric.get("max")
    mean = metric.get("mean")

    if not isinstance(delta, (int, float)):
        metric.setdefault("first", None)
        metric.setdefault("last", None)
        return

    if delta > 0 and isinstance(minimum, (int, float)):
        first = float(minimum)
        last = first + float(delta)
    elif delta < 0 and isinstance(maximum, (int, float)):
        first = float(maximum)
        last = first + float(delta)
    elif isinstance(mean, (int, float)):
        first = float(mean)
        last = float(mean)
    else:
        first = None
        last = None

    metric["first"] = first
    metric["last"] = last


def _walk_add_endpoints(value: Any) -> None:
    if isinstance(value, dict):
        _add_endpoints(value)
        for child in value.values():
            _walk_add_endpoints(child)
    elif isinstance(value, list):
        for child in value:
            _walk_add_endpoints(child)


def base_packet_v11_5() -> dict[str, Any]:
    packet = deepcopy(_legacy_base_packet())

    capabilities = packet["measurement_capabilities"]
    capabilities["not_provided_by_system"] = ["co2", "airflow"]
    capabilities["excluded_from_current_analysis_packet"] = [
        "fan_rpm",
        "tacho",
    ]

    for node in packet["sensor_bus"]["nodes"].values():
        deltas = node["diagnostic_counter_deltas"]
        deltas.pop("consecutive_failures", None)
        node["consecutive_failures_max"] = 0

    _walk_add_endpoints(packet)
    return packet


def load_scenarios_v11_5() -> list[dict[str, Any]]:
    scenarios = deepcopy(_legacy_load_scenarios())

    for scenario in scenarios:
        scenario_id = scenario.get("id")

        if scenario_id == "sensor_node_degraded":
            node = scenario["overrides"]["sensor_bus"]["nodes"]["1"]
            deltas = node.get("diagnostic_counter_deltas", {})
            previous = deltas.pop("consecutive_failures", None)
            node["consecutive_failures_max"] = 4 if previous is None else previous

        if scenario_id == "missing_voc_on_one_node":
            for rule in scenario.get("must_not_match", []):
                if rule.get("name") == "does_not_invent_missing_voc_value":
                    rule["pattern"] = (
                        r"(?:(?:węzeł|węźle|node|adres|SEN55).{0,20}"
                        r"(?:2|drugi|drugiego).{0,45}VOC Index.{0,25}"
                        r"(?:wynosi|średni|maksymaln).{0,8}[1-9][0-9]*)"
                    )

        _walk_add_endpoints(scenario.get("overrides", {}))

    scenarios.extend(
        [
            {
                "id": "non_monotonic_chronology",
                "description": (
                    "VOC ma ekstrema daleko od chronologicznych first/last; model nie może "
                    "opisywać min/max jako początku i końca."
                ),
                "allowed_status": ["attention", "anomaly"],
                "overrides": {
                    "sensor_bus": {
                        "nodes": {
                            "1": {
                                "readings": {
                                    "voc_index": {
                                        "count": 180,
                                        "missing": 0,
                                        "mean": 220.0,
                                        "min": 24.0,
                                        "max": 416.0,
                                        "first": 140.0,
                                        "last": 256.0,
                                        "delta": 116.0,
                                        "slope_per_minute": -3.279,
                                    }
                                }
                            }
                        }
                    }
                },
                "must_match": [
                    {
                        "name": "detects_voc_event",
                        "field": "analysis_pl",
                        "patterns": ["VOC"],
                    }
                ],
                "must_not_match": [
                    {
                        "name": "does_not_use_min_max_as_chronological_endpoints",
                        "field": "all",
                        "pattern": (
                            r"VOC Index.{0,60}(?:z|od)\s*24(?:[.,]0)?\s*"
                            r"(?:do|na|→)\s*416(?:[.,]0)?"
                        ),
                    }
                ],
            },
            {
                "id": "partial_missing_samples",
                "description": (
                    "Jeden kanał VOC ma 10 brakujących próbek; model nie może nazywać "
                    "tego kanału kompletnym."
                ),
                "allowed_status": ["no_anomaly_detected", "attention"],
                "overrides": {
                    "sensor_bus": {
                        "nodes": {
                            "2": {
                                "readings": {
                                    "voc_index": {
                                        "count": 170,
                                        "missing": 10,
                                        "mean": 95.0,
                                        "min": 90.0,
                                        "max": 100.0,
                                        "first": 95.0,
                                        "last": 96.0,
                                        "delta": 1.0,
                                        "slope_per_minute": 0.02,
                                    }
                                }
                            }
                        }
                    }
                },
                "must_match": [
                    {
                        "name": "reports_partial_missing_samples",
                        "field": "data_quality_pl",
                        "mode": "all",
                        "patterns": ["VOC", "10|brak|niepeł"],
                    }
                ],
                "must_not_match": [
                    {
                        "name": "does_not_claim_zero_missing_samples",
                        "field": "data_quality_pl",
                        "pattern": r"brak brakujących próbek|0 brakujących próbek",
                    }
                ],
            },
            {
                "id": "active_alarm_named_in_analysis",
                "description": (
                    "Aktywny AERO_BUS_UNAVAILABLE musi być nazwany w analysis_pl jako "
                    "konkretna podstawa statusu anomaly."
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
                    }
                },
                "must_match": [
                    {
                        "name": "names_alarm_in_analysis",
                        "field": "analysis_pl",
                        "patterns": ["AERO_BUS_UNAVAILABLE"],
                    }
                ],
                "must_not_match": [],
            },
        ]
    )

    return scenarios


base.base_packet = base_packet_v11_5
base.load_scenarios = load_scenarios_v11_5


if __name__ == "__main__":
    raise SystemExit(base.main())
