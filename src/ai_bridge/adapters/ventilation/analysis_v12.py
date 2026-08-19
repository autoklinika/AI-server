from __future__ import annotations

"""Ventilation analysis v12: Qwen decides, Python renders grounded facts.

The model no longer writes operator-facing prose or copies telemetry numbers into
free text. Python builds an immutable fact catalog from the deterministic compact
packet. Qwen returns only a small structured decision: status, reason codes,
selected fact IDs, and one recommendation code. Python validates those IDs and
renders the final ``VentilationAnalysisResult`` directly from the source facts.

This keeps interpretation/advisory selection in the model while making numerical
and subsystem wording deterministic and auditable.
"""

import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from ai_bridge.adapters.ventilation.analysis_profile import build_compact_analysis_packet
from ai_bridge.analysis.schemas import VentilationAnalysisResult


PROMPT_VERSION = "ventilation-v12-structured-decision"
ANALYSIS_THINK = False
MAX_SELECTED_FACTS = 8

Status = Literal[
    "no_anomaly_detected",
    "attention",
    "anomaly",
    "insufficient_data",
]
ReasonCode = Literal[
    "no_significant_issue",
    "environmental_change",
    "technical_alarm",
    "technical_degradation",
    "data_quality_issue",
]
RecommendationCode = Literal[
    "none",
    "observe_next_windows",
    "diagnose_active_alarm",
]


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class VentilationDecisionV12(_StrictModel):
    schema_version: Literal[1] = 1
    status: Status
    reason_codes: list[ReasonCode] = Field(min_length=1, max_length=4)
    selected_fact_ids: list[str] = Field(default_factory=list, max_length=MAX_SELECTED_FACTS)
    recommendation_code: RecommendationCode


SYSTEM_PROMPT = """Jesteś lokalnym analitykiem systemu wentylacji warsztatu.

Dostajesz listę WYŁĄCZNIE deterministycznych faktów z jednego zamkniętego
15-minutowego okna. Nie tworzysz raportu tekstowego i nie przepisujesz liczb.
Twoim zadaniem jest tylko podjąć małą, ustrukturyzowaną decyzję.

Zwróć wyłącznie JSON zgodny ze schematem:
- status,
- reason_codes,
- selected_fact_ids,
- recommendation_code.

Reguły:
- selected_fact_ids mogą zawierać tylko identyfikatory dokładnie obecne w `facts`;
  wybierz najwyżej 8 najważniejszych faktów dla swojej decyzji,
- `no_anomaly_detected`: brak jednoznacznej anomalii technicznej, istotnego
  problemu jakości danych i wyraźnej zmiany wymagającej uwagi,
- `attention`: wyraźny trend/zmiana środowiskowa albo istotny częściowy problem
  jakości danych bez potwierdzonej awarii,
- `anomaly`: konkretna anomalia techniczna potwierdzona faktami, np. aktywny alarm,
  FAULT, utrata gotowości SENSOR BUS, awaria workera lub wyraźna degradacja
  komunikacji,
- `insufficient_data`: danych jest zasadniczo za mało do analizy; sam brak
  historycznego baseline'u nie oznacza insufficient_data,
- jeśli istnieje fakt `active_alarm`, status musi być `anomaly`, reason_codes musi
  zawierać `technical_alarm`, a selected_fact_ids musi zawierać co najmniej jeden
  fakt aktywnego alarmu,
- expected_operating_state_known=false samo w sobie nigdy nie podnosi statusu;
  STOP i setpointy 0 V nie są same w sobie awarią,
- `missing > 0` jest problemem jakości danego kanału; pełny brak kanału przez całe
  okno wymaga co najmniej `attention`,
- nie wnioskuj o przyczynowości, źródłach emisji, przepływie ani RPM z samych
  setpointów; wybierasz fakty, nie tworzysz historii przyczynowej,
- recommendation_code:
  * `diagnose_active_alarm` tylko gdy istnieje aktywny alarm,
  * `observe_next_windows` dla trendu wymagającego uwagi bez konkretnej awarii,
  * `none` gdy z bieżącego okna nie wynika dodatkowa czynność,
- przy `no_anomaly_detected` użyj reason_codes=["no_significant_issue"] i
  recommendation_code="none".
"""


def _fact(fact_id: str, kind: str, **payload: Any) -> dict[str, Any]:
    return {"id": fact_id, "kind": kind, **payload}


def build_fact_catalog(packet: dict[str, Any]) -> list[dict[str, Any]]:
    """Build stable model-selectable facts from a v11 compact packet."""

    facts: list[dict[str, Any]] = []
    controller = packet.get("controller", {}) if isinstance(packet.get("controller"), dict) else {}
    sensor_bus = packet.get("sensor_bus", {}) if isinstance(packet.get("sensor_bus"), dict) else {}

    facts.append(
        _fact(
            "controller:mode",
            "controller_mode",
            latest_mode=controller.get("latest_mode"),
            mode_counts=controller.get("mode_counts", {}),
        )
    )

    setpoints = controller.get("setpoints", {}) if isinstance(controller.get("setpoints"), dict) else {}
    for channel in ("supply_voltage", "extract_voltage"):
        metric = setpoints.get(channel, {}) if isinstance(setpoints.get(channel), dict) else {}
        facts.append(
            _fact(
                f"controller:setpoint:{channel}",
                "setpoint",
                channel=channel,
                first=metric.get("first"),
                last=metric.get("last"),
                delta=metric.get("delta"),
                mean=metric.get("mean"),
                min=metric.get("min"),
                max=metric.get("max"),
            )
        )

    alarm_codes = controller.get("active_alarm_codes", [])
    if not isinstance(alarm_codes, list):
        alarm_codes = []
    facts.append(
        _fact(
            "controller:alarms",
            "alarm_overview",
            active_alarm_sample_count=controller.get("active_alarm_sample_count"),
            active_alarm_codes=alarm_codes,
        )
    )
    for code in alarm_codes:
        facts.append(
            _fact(
                f"alarm:{code}",
                "active_alarm",
                code=code,
            )
        )

    facts.append(
        _fact(
            "sensor_bus:health",
            "sensor_bus_health",
            ready_ratio=sensor_bus.get("ready_ratio"),
            worker_alive_ratio=sensor_bus.get("worker_alive_ratio"),
            worker_restarts_max=sensor_bus.get("worker_restarts_max"),
            latest_error=sensor_bus.get("latest_error"),
        )
    )

    nodes = sensor_bus.get("nodes", {}) if isinstance(sensor_bus.get("nodes"), dict) else {}
    for node_id in sorted(nodes, key=str):
        node = nodes[node_id] if isinstance(nodes[node_id], dict) else {}
        facts.append(
            _fact(
                f"node:{node_id}:health",
                "node_health",
                node_id=str(node_id),
                online_ratio=node.get("online_ratio"),
                measurement_valid_ratio=node.get("measurement_valid_ratio"),
                measurement_stale_ratio=node.get("measurement_stale_ratio"),
                consecutive_failures_max=node.get("consecutive_failures_max"),
                diagnostic_counter_deltas=node.get("diagnostic_counter_deltas", {}),
                latest_error=node.get("latest_error"),
            )
        )

        readings = node.get("readings", {}) if isinstance(node.get("readings"), dict) else {}
        for channel in sorted(readings):
            metric = readings[channel] if isinstance(readings[channel], dict) else {}
            facts.append(
                _fact(
                    f"node:{node_id}:reading:{channel}",
                    "reading",
                    node_id=str(node_id),
                    channel=channel,
                    count=metric.get("count"),
                    missing=metric.get("missing"),
                    mean=metric.get("mean"),
                    min=metric.get("min"),
                    max=metric.get("max"),
                    first=metric.get("first"),
                    last=metric.get("last"),
                    delta=metric.get("delta"),
                    slope_per_minute=metric.get("slope_per_minute"),
                )
            )

    return facts


def build_decision_packet_from_compact(packet: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "window": packet.get("window", {}),
        "analysis_context": packet.get("analysis_context", {}),
        "measurement_capabilities": packet.get("measurement_capabilities", {}),
        "facts": build_fact_catalog(packet),
    }


def build_decision_prompt_from_compact(packet: dict[str, Any]) -> list[dict[str, str]]:
    model_packet = build_decision_packet_from_compact(packet)
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"Wersja profilu: {PROMPT_VERSION}\n\n"
                + json.dumps(model_packet, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            ),
        },
    ]


def build_decision_prompt(summary: dict[str, Any]) -> list[dict[str, str]]:
    return build_decision_prompt_from_compact(build_compact_analysis_packet(summary))


def validate_decision(
    packet: dict[str, Any],
    decision: VentilationDecisionV12,
) -> VentilationDecisionV12:
    catalog = build_fact_catalog(packet)
    by_id = {fact["id"]: fact for fact in catalog}

    if len(decision.selected_fact_ids) != len(set(decision.selected_fact_ids)):
        raise ValueError("v12 decision contains duplicate selected_fact_ids")

    unknown = [fact_id for fact_id in decision.selected_fact_ids if fact_id not in by_id]
    if unknown:
        raise ValueError(f"v12 decision selected unknown fact IDs: {unknown}")

    active_alarm_ids = {
        fact["id"] for fact in catalog if fact.get("kind") == "active_alarm"
    }
    if active_alarm_ids:
        if decision.status != "anomaly":
            raise ValueError("active alarm requires v12 status='anomaly'")
        if "technical_alarm" not in decision.reason_codes:
            raise ValueError("active alarm requires reason code 'technical_alarm'")
        if not active_alarm_ids.intersection(decision.selected_fact_ids):
            raise ValueError("active alarm requires selecting at least one alarm fact")

    if decision.recommendation_code == "diagnose_active_alarm" and not active_alarm_ids:
        raise ValueError("diagnose_active_alarm recommendation requires an active alarm")

    if decision.status == "no_anomaly_detected":
        if decision.reason_codes != ["no_significant_issue"]:
            raise ValueError(
                "no_anomaly_detected requires reason_codes=['no_significant_issue']"
            )
        if decision.recommendation_code != "none":
            raise ValueError("no_anomaly_detected requires recommendation_code='none'")

    return decision


_CHANNEL_LABELS = {
    "pm1_0_ug_m3": "PM1.0",
    "pm2_5_ug_m3": "PM2.5",
    "pm4_0_ug_m3": "PM4.0",
    "pm10_0_ug_m3": "PM10.0",
    "humidity_percent": "wilgotność",
    "temperature_celsius": "temperatura",
    "voc_index": "VOC Index",
    "nox_index": "NOx Index",
}


def _fmt(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, float):
        text = f"{value:.4f}".rstrip("0").rstrip(".")
        return text.replace(".", ",")
    return str(value)


def _unit(channel: str) -> str:
    if channel.startswith("pm"):
        return " µg/m³"
    if channel == "humidity_percent":
        return " %"
    if channel == "temperature_celsius":
        return " °C"
    return ""


def _render_fact(fact: dict[str, Any]) -> str:
    kind = fact.get("kind")
    if kind == "controller_mode":
        return f"Tryb sterownika: {_fmt(fact.get('latest_mode'))}."
    if kind == "setpoint":
        channel = str(fact.get("channel"))
        return (
            f"{channel}: first={_fmt(fact.get('first'))} V, "
            f"last={_fmt(fact.get('last'))} V, delta={_fmt(fact.get('delta'))} V."
        )
    if kind == "active_alarm":
        return f"Aktywny alarm: {fact.get('code')}."
    if kind == "alarm_overview":
        codes = fact.get("active_alarm_codes") or []
        return (
            "Alarmy sterownika: "
            f"active_alarm_sample_count={_fmt(fact.get('active_alarm_sample_count'))}, "
            f"active_alarm_codes={','.join(str(code) for code in codes) if codes else 'brak'}."
        )
    if kind == "sensor_bus_health":
        return (
            "SENSOR BUS: "
            f"ready_ratio={_fmt(fact.get('ready_ratio'))}, "
            f"worker_alive_ratio={_fmt(fact.get('worker_alive_ratio'))}, "
            f"worker_restarts_max={_fmt(fact.get('worker_restarts_max'))}."
        )
    if kind == "node_health":
        return (
            f"Węzeł {fact.get('node_id')}: online_ratio={_fmt(fact.get('online_ratio'))}, "
            f"measurement_valid_ratio={_fmt(fact.get('measurement_valid_ratio'))}, "
            f"measurement_stale_ratio={_fmt(fact.get('measurement_stale_ratio'))}, "
            f"consecutive_failures_max={_fmt(fact.get('consecutive_failures_max'))}."
        )
    if kind == "reading":
        channel = str(fact.get("channel"))
        label = _CHANNEL_LABELS.get(channel, channel)
        unit = _unit(channel)
        return (
            f"Węzeł {fact.get('node_id')}, {label}: "
            f"first={_fmt(fact.get('first'))}{unit}, "
            f"last={_fmt(fact.get('last'))}{unit}, "
            f"delta={_fmt(fact.get('delta'))}{unit}, "
            f"slope_per_minute={_fmt(fact.get('slope_per_minute'))}, "
            f"missing={_fmt(fact.get('missing'))}."
        )
    return f"Fakt {fact.get('id')}."


def render_data_quality(packet: dict[str, Any]) -> str:
    sensor_bus = packet.get("sensor_bus", {}) if isinstance(packet.get("sensor_bus"), dict) else {}
    nodes = sensor_bus.get("nodes", {}) if isinstance(sensor_bus.get("nodes"), dict) else {}
    missing_items: list[str] = []

    for node_id in sorted(nodes, key=str):
        node = nodes[node_id] if isinstance(nodes[node_id], dict) else {}
        readings = node.get("readings", {}) if isinstance(node.get("readings"), dict) else {}
        for channel in sorted(readings):
            metric = readings[channel] if isinstance(readings[channel], dict) else {}
            missing = metric.get("missing")
            if isinstance(missing, (int, float)) and missing > 0:
                label = _CHANNEL_LABELS.get(channel, channel)
                missing_items.append(f"węzeł {node_id}, {label}: missing={_fmt(missing)}")

    if missing_items:
        quality = "Braki danych: " + "; ".join(missing_items) + "."
    else:
        quality = "Wszystkie kanały pomiarowe obecne w pakiecie mają missing=0."

    capabilities = packet.get("measurement_capabilities", {})
    if isinstance(capabilities, dict):
        excluded = capabilities.get("excluded_from_current_analysis_packet", [])
        not_provided = capabilities.get("not_provided_by_system", [])
        if isinstance(excluded, list) and any(item in excluded for item in ("fan_rpm", "tacho")):
            quality += " TACHO/RPM są wyłączone z bieżącego pakietu analitycznego."
        if isinstance(not_provided, list) and any(item in not_provided for item in ("co2", "airflow")):
            quality += " CO2 i przepływ nie są dostarczane do tego profilu analitycznego."

    return quality


def render_result(
    packet: dict[str, Any],
    decision: VentilationDecisionV12,
) -> VentilationAnalysisResult:
    decision = validate_decision(packet, decision)
    catalog = build_fact_catalog(packet)
    by_id = {fact["id"]: fact for fact in catalog}

    rendered = [_render_fact(by_id[fact_id]) for fact_id in decision.selected_fact_ids]
    if rendered:
        analysis = " ".join(rendered)
    else:
        analysis = "W bieżącym oknie model nie wskazał dodatkowych faktów wymagających wyróżnienia."

    context = packet.get("analysis_context", {})
    if isinstance(context, dict) and context.get("historical_baseline_available") is False:
        analysis += (
            " Brak historycznego baseline'u uniemożliwia klasyfikację wartości "
            "względem normalnej pracy warsztatu."
        )
    if isinstance(context, dict) and context.get("expected_operating_state_known") is False:
        analysis += (
            " Oczekiwany stan operacyjny nie jest znany; sam tryb i setpointy nie są "
            "na tej podstawie traktowane jako awaria."
        )

    if decision.recommendation_code == "none":
        recommendation = "Na podstawie tego okna nie ma dodatkowych zaleceń."
    elif decision.recommendation_code == "observe_next_windows":
        recommendation = (
            "Obserwować kolejne okna telemetryczne w celu oceny dalszego przebiegu "
            "wybranych trendów."
        )
    else:
        alarm_codes = [
            fact.get("code")
            for fact in catalog
            if fact.get("kind") == "active_alarm"
        ]
        recommendation = (
            "Przeprowadzić diagnostykę aktywnych alarmów zgodnie z dokumentacją "
            "systemu CM5: " + ", ".join(str(code) for code in alarm_codes) + "."
        )

    return VentilationAnalysisResult(
        status=decision.status,
        analysis_pl=analysis,
        operator_recommendation_pl=recommendation,
        data_quality_pl=render_data_quality(packet),
    )
