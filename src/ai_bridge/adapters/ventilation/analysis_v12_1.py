from __future__ import annotations

"""Ventilation analysis v12.1: model interprets environment, Python owns hard facts.

The v12 fast gate showed that even a small status schema can still let the model
invent a technical alarm or overlook a data-quality defect. v12.1 removes those
classes of decisions from the model entirely.

Qwen now decides only whether the environmental measurements in the current
window deserve attention and which environmental facts are worth highlighting.
Python deterministically owns active alarms, data quality, technical-health floors,
final status hierarchy, recommendation code and all operator-facing rendering.
"""

import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from ai_bridge.adapters.ventilation import analysis_v12 as base
from ai_bridge.analysis.schemas import VentilationAnalysisResult


PROMPT_VERSION = "ventilation-v12.1-grounded-decision"
ANALYSIS_THINK = False
MAX_SELECTED_FACTS = 6


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EnvironmentalDecisionV121(_StrictModel):
    schema_version: Literal[1] = 1
    environmental_attention: bool
    selected_fact_ids: list[str] = Field(default_factory=list, max_length=MAX_SELECTED_FACTS)


SYSTEM_PROMPT = """Jesteś lokalnym analitykiem danych środowiskowych wentylacji warsztatu.

Dostajesz tylko fakty środowiskowe i kontekst sterowania z jednego zamkniętego
15-minutowego okna. Nie oceniasz alarmów technicznych, jakości transmisji,
brakujących próbek ani stanu SENSOR BUS — te rzeczy rozstrzyga deterministycznie
Python poza modelem.

Twoje jedyne zadanie:
1. ustaw `environmental_attention=true`, jeżeli w bieżącym oknie występuje
   wyraźna zmiana/trend pomiarów środowiskowych zasługujący na uwagę operatora,
   w przeciwnym razie false,
2. wybierz maksymalnie 6 `selected_fact_ids` spośród identyfikatorów dokładnie
   obecnych w `facts`, które najlepiej uzasadniają tę ocenę.

Reguły:
- nie twórz statusu anomaly i nie interpretuj kodów alarmów — nie są częścią tego
  zadania,
- brak historycznego baseline'u nie oznacza automatycznie attention,
- STOP i setpointy 0 V same w sobie nie oznaczają problemu,
- setpoint 0-10 V jest tylko zadanym sygnałem sterującym; nie jest przepływem ani
  zmierzoną wydajnością wentylacji,
- nie wnioskuj o przyczynowości, źródle emisji ani wpływie setpointów na pomiary,
- VOC Index jest indeksem czujnika, nie bezpośrednim pomiarem emisji,
- `slope_per_minute` jest współczynnikiem regresji liniowej całego okna,
- wartości `first`, `last`, `delta`, `min`, `max`, `mean` opisują wyłącznie bieżący
  fakt i nie wolno przenosić liczb między kanałami lub węzłami,
- zwróć wyłącznie JSON zgodny ze schematem.
"""


def build_environment_fact_catalog(packet: dict[str, Any]) -> list[dict[str, Any]]:
    """Return only facts the model is allowed to interpret semantically."""

    allowed_kinds = {"controller_mode", "setpoint", "reading"}
    result: list[dict[str, Any]] = []
    for fact in base.build_fact_catalog(packet):
        if fact.get("kind") not in allowed_kinds:
            continue
        clean = dict(fact)
        # Missing/count are handled by Python data-quality logic, not by Qwen.
        if clean.get("kind") == "reading":
            clean.pop("missing", None)
            clean.pop("count", None)
        result.append(clean)
    return result


def build_environment_packet_from_compact(packet: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "window": packet.get("window", {}),
        "analysis_context": packet.get("analysis_context", {}),
        "facts": build_environment_fact_catalog(packet),
    }


def build_environment_prompt_from_compact(packet: dict[str, Any]) -> list[dict[str, str]]:
    model_packet = build_environment_packet_from_compact(packet)
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"Wersja profilu: {PROMPT_VERSION}\n\n"
                + json.dumps(
                    model_packet,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
            ),
        },
    ]


def validate_environmental_decision(
    packet: dict[str, Any],
    decision: EnvironmentalDecisionV121,
) -> EnvironmentalDecisionV121:
    eligible_ids = {fact["id"] for fact in build_environment_fact_catalog(packet)}
    if len(decision.selected_fact_ids) != len(set(decision.selected_fact_ids)):
        raise ValueError("v12.1 decision contains duplicate selected_fact_ids")
    unknown = [fact_id for fact_id in decision.selected_fact_ids if fact_id not in eligible_ids]
    if unknown:
        raise ValueError(f"v12.1 decision selected unknown environmental fact IDs: {unknown}")
    return decision


def _controller(packet: dict[str, Any]) -> dict[str, Any]:
    value = packet.get("controller", {})
    return value if isinstance(value, dict) else {}


def _sensor_bus(packet: dict[str, Any]) -> dict[str, Any]:
    value = packet.get("sensor_bus", {})
    return value if isinstance(value, dict) else {}


def _active_alarm_ids(packet: dict[str, Any]) -> list[str]:
    codes = _controller(packet).get("active_alarm_codes", [])
    if not isinstance(codes, list):
        return []
    return [f"alarm:{code}" for code in codes]


def _missing_present(packet: dict[str, Any]) -> bool:
    nodes = _sensor_bus(packet).get("nodes", {})
    if not isinstance(nodes, dict):
        return False
    for node in nodes.values():
        if not isinstance(node, dict):
            continue
        readings = node.get("readings", {})
        if not isinstance(readings, dict):
            continue
        for metric in readings.values():
            if not isinstance(metric, dict):
                continue
            missing = metric.get("missing")
            if isinstance(missing, (int, float)) and missing > 0:
                return True
    return False


def _health_assessment(packet: dict[str, Any]) -> tuple[bool, bool, list[str]]:
    """Return (hard_failure, degraded, grounded health fact ids)."""

    hard_failure = False
    degraded = False
    selected: list[str] = []
    bus = _sensor_bus(packet)

    ready = bus.get("ready_ratio")
    worker = bus.get("worker_alive_ratio")
    restarts = bus.get("worker_restarts_max")
    latest_error = bus.get("latest_error")

    bus_problem = False
    for value in (ready, worker):
        if isinstance(value, (int, float)):
            if value == 0:
                hard_failure = True
                bus_problem = True
            elif value < 1:
                degraded = True
                bus_problem = True
    if isinstance(restarts, (int, float)) and restarts > 0:
        degraded = True
        bus_problem = True
    if latest_error not in (None, ""):
        degraded = True
        bus_problem = True
    if bus_problem:
        selected.append("sensor_bus:health")

    nodes = bus.get("nodes", {})
    if isinstance(nodes, dict):
        for node_id, node in nodes.items():
            if not isinstance(node, dict):
                continue
            node_problem = False
            for key in ("online_ratio", "measurement_valid_ratio"):
                value = node.get(key)
                if isinstance(value, (int, float)) and value < 1:
                    degraded = True
                    node_problem = True
            stale = node.get("measurement_stale_ratio")
            if isinstance(stale, (int, float)) and stale > 0:
                degraded = True
                node_problem = True
            consecutive = node.get("consecutive_failures_max")
            if isinstance(consecutive, (int, float)) and consecutive > 0:
                degraded = True
                node_problem = True
            deltas = node.get("diagnostic_counter_deltas", {})
            if isinstance(deltas, dict) and any(
                isinstance(value, (int, float)) and value > 0
                for value in deltas.values()
            ):
                degraded = True
                node_problem = True
            if node.get("latest_error") not in (None, ""):
                degraded = True
                node_problem = True
            if node_problem:
                selected.append(f"node:{node_id}:health")

    return hard_failure, degraded, selected


def resolve_final_decision(
    packet: dict[str, Any],
    environmental: EnvironmentalDecisionV121,
) -> base.VentilationDecisionV12:
    """Apply deterministic safety/data-quality floors around Qwen interpretation."""

    validate_environmental_decision(packet, environmental)

    alarm_ids = _active_alarm_ids(packet)
    missing = _missing_present(packet)
    hard_failure, degraded, health_ids = _health_assessment(packet)

    reasons: list[str] = []
    if alarm_ids:
        reasons.append("technical_alarm")
    if hard_failure or degraded:
        reasons.append("technical_degradation")
    if missing:
        reasons.append("data_quality_issue")
    if environmental.environmental_attention:
        reasons.append("environmental_change")

    if alarm_ids or hard_failure:
        status = "anomaly"
    elif degraded or missing or environmental.environmental_attention:
        status = "attention"
    else:
        status = "no_anomaly_detected"
        reasons = ["no_significant_issue"]

    if alarm_ids:
        recommendation = "diagnose_active_alarm"
    elif environmental.environmental_attention:
        recommendation = "observe_next_windows"
    else:
        recommendation = "none"

    selected: list[str] = []
    # Deterministic evidence has priority over model-selected environmental context.
    for fact_id in [*alarm_ids, *health_ids, *environmental.selected_fact_ids]:
        if fact_id not in selected:
            selected.append(fact_id)
        if len(selected) >= base.MAX_SELECTED_FACTS:
            break

    return base.VentilationDecisionV12(
        status=status,
        reason_codes=reasons,
        selected_fact_ids=selected,
        recommendation_code=recommendation,
    )


def render_result(
    packet: dict[str, Any],
    environmental: EnvironmentalDecisionV121,
) -> VentilationAnalysisResult:
    return base.render_result(packet, resolve_final_decision(packet, environmental))
