from __future__ import annotations

"""Temporary v11.4 benchmark entrypoint.

It reuses the established benchmark engine from run.py while aligning the
synthetic packet and the affected scenario checks with the v11.4 production
compact-packet contract. This keeps the historical v11.3 runner unchanged
while v11.4 is being validated.
"""

from copy import deepcopy

import run as base


_legacy_base_packet = base.base_packet
_legacy_load_scenarios = base.load_scenarios


def base_packet_v11_4():
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

    return packet


def load_scenarios_v11_4():
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
                    # Node 1 legitimately has VOC values. Only reject a numeric
                    # VOC value explicitly attributed to the missing node 2.
                    rule["pattern"] = (
                        r"(?:(?:węzeł|węźle|node|adres|SEN55).{0,20}"
                        r"(?:2|drugi|drugiego).{0,80}VOC Index.{0,30}"
                        r"(?:wynosi|średni|maksymaln).{0,10}[1-9][0-9]*|"
                        r"VOC Index.{0,30}(?:wynosi|średni|maksymaln).{0,10}"
                        r"[1-9][0-9]*.{0,80}(?:węzeł|węźle|node|adres|SEN55)"
                        r".{0,20}(?:2|drugi|drugiego))"
                    )

    return scenarios


base.base_packet = base_packet_v11_4
base.load_scenarios = load_scenarios_v11_4


if __name__ == "__main__":
    raise SystemExit(base.main())
