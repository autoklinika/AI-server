from __future__ import annotations

import json
from typing import Any

import pytest

from ai_bridge.analysis.schemas import (
    AnalysisEvidenceReference,
    AnalysisObservation,
    VentilationAnalysisResult,
)
from ai_bridge.analysis.service import (
    _required_provenance_paths,
    validate_analysis_provenance,
)


def _summary() -> dict[str, Any]:
    def node(pm25: float, pm25_delta: float, pm10: float, pm10_delta: float, voc: float, voc_delta: float):
        return {
            "online_true_ratio": 1.0,
            "measurement_valid_true_ratio": 1.0,
            "readings": {
                "pm2_5_ug_m3": {
                    "mean": pm25,
                    "delta": pm25_delta,
                    "slope_per_minute": -0.12,
                },
                "pm10_0_ug_m3": {
                    "mean": pm10,
                    "delta": pm10_delta,
                    "slope_per_minute": -0.12,
                },
                "voc_index": {
                    "mean": voc,
                    "delta": voc_delta,
                    "slope_per_minute": 0.9,
                },
                "temperature_celsius": {"mean": 25.0, "delta": 0.2},
                "humidity_percent": {"mean": 43.0, "delta": 0.3},
            },
        }

    return {
        "analysis_context": {
            "historical_baseline_available": False,
            "expected_operating_state_known": False,
        },
        "system": {
            "latest_mode": "STOP",
            "setpoints": {
                "supply_voltage": {"mean": 0.0},
                "extract_voltage": {"mean": 0.0},
            },
            "active_alarm_sample_count": 0,
        },
        "sensor_bus": {
            "ready_true_ratio": 1.0,
            "worker_alive_true_ratio": 1.0,
            "nodes": {
                "1": node(6.9, -2.0, 6.9, -2.0, 21.1, 16.0),
                "2": node(6.6, -2.4, 6.6, -2.4, 20.4, 14.0),
            },
        },
    }


def _resolve(summary: dict[str, Any], path: str) -> Any:
    current: Any = summary
    for part in path.split("."):
        current = current[part]
    return current


def _references(summary: dict[str, Any]) -> list[AnalysisEvidenceReference]:
    return [
        AnalysisEvidenceReference(
            path=path,
            value_json=json.dumps(
                _resolve(summary, path),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
        )
        for path in sorted(_required_provenance_paths(summary))
    ]


def _valid_result(summary: dict[str, Any]) -> VentilationAnalysisResult:
    air_paths = [
        "sensor_bus.nodes.1.readings.pm2_5_ug_m3.delta",
        "sensor_bus.nodes.1.readings.voc_index.delta",
        "sensor_bus.nodes.2.readings.pm2_5_ug_m3.delta",
        "sensor_bus.nodes.2.readings.voc_index.delta",
    ]
    return VentilationAnalysisResult(
        status="normal",
        summary="Brak sklasyfikowanej anomalii; widoczne są kierunkowe trendy w oknie.",
        confidence=0.7,
        observations=[
            AnalysisObservation(
                title="Stan sterownika i SENSOR BUS",
                importance="low",
                evidence=["Sterownik był w STOP, a SENSOR BUS był dostępny."],
                provenance_paths=[
                    "system.latest_mode",
                    "sensor_bus.ready_true_ratio",
                ],
            ),
            AnalysisObservation(
                title="Trendy PM i VOC",
                importance="medium",
                evidence=["PM2.5 spadało, a VOC rosło na obu węzłach."],
                provenance_paths=air_paths,
            ),
        ],
        provenance=_references(summary),
    )


def test_provenance_accepts_exact_paths_and_values() -> None:
    summary = _summary()
    validate_analysis_provenance(summary, _valid_result(summary))


def test_provenance_rejects_invented_path() -> None:
    summary = _summary()
    result = _valid_result(summary)
    result.provenance.append(
        AnalysisEvidenceReference(path="sensor_data.latest.mode", value_json='"STOP"')
    )
    with pytest.raises(ValueError, match="does not exist"):
        validate_analysis_provenance(summary, result)


def test_provenance_rejects_wrong_value() -> None:
    summary = _summary()
    result = _valid_result(summary)
    result.provenance[0] = AnalysisEvidenceReference(
        path=result.provenance[0].path,
        value_json="123456",
    )
    with pytest.raises(ValueError, match="does not match"):
        validate_analysis_provenance(summary, result)


def test_provenance_rejects_missing_required_metric() -> None:
    summary = _summary()
    result = _valid_result(summary)
    missing = "sensor_bus.nodes.2.readings.voc_index.slope_per_minute"
    result.provenance = [ref for ref in result.provenance if ref.path != missing]
    with pytest.raises(ValueError, match="incomplete"):
        validate_analysis_provenance(summary, result)


def test_observations_must_cover_pm25_and_voc_delta_for_each_node() -> None:
    summary = _summary()
    result = _valid_result(summary)
    target = "sensor_bus.nodes.2.readings.voc_index.delta"
    result.observations[1].provenance_paths = [
        path for path in result.observations[1].provenance_paths if path != target
    ]
    with pytest.raises(ValueError, match="missing coverage"):
        validate_analysis_provenance(summary, result)
