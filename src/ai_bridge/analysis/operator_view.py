from __future__ import annotations

from typing import Any

from ai_bridge.analysis.schemas import VentilationOperatorView


_STATUS_LABELS = {
    "no_anomaly_detected": "BRAK ANOMALII",
    "attention": "WYMAGA UWAGI",
    "anomaly": "ANOMALIA",
    "insufficient_data": "NIEWYSTARCZAJĄCE DANE",
}

_CHANNEL_LABELS = {
    "pm1_0_ug_m3": "PM1.0",
    "pm2_5_ug_m3": "PM2.5",
    "pm4_0_ug_m3": "PM4.0",
    "pm10_0_ug_m3": "PM10.0",
    "humidity_percent": "Wilgotność",
    "temperature_celsius": "Temperatura",
    "voc_index": "VOC Index",
    "nox_index": "NOx Index",
}


def _fmt(value: Any, *, max_digits: int = 1) -> str:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return "—"
    numeric = float(value)
    if numeric.is_integer():
        return str(int(numeric))
    return f"{numeric:.{max_digits}f}".rstrip("0").rstrip(".").replace(".", ",")


def _unit(channel: str) -> str:
    if channel.startswith("pm"):
        return " µg/m³"
    if channel == "humidity_percent":
        return " %"
    if channel == "temperature_celsius":
        return " °C"
    return ""


def _zone_label(node_id: Any) -> str:
    return f"strefa {node_id}"


def _baseline_suffix(packet: dict[str, Any]) -> str:
    context = packet.get("analysis_context", {})
    if isinstance(context, dict) and context.get("historical_baseline_available") is False:
        return (
            " Brak historycznego punktu odniesienia, dlatego wynik opisuje zmianę "
            "w tym oknie, a nie odchylenie od typowej pracy warsztatu."
        )
    return ""


def _reading_sentence(fact: dict[str, Any]) -> str:
    channel = str(fact.get("channel"))
    label = _CHANNEL_LABELS.get(channel, channel)
    unit = _unit(channel)
    zone = _zone_label(fact.get("node_id"))
    first = fact.get("first")
    last = fact.get("last")
    delta = fact.get("delta")

    if isinstance(first, (int, float)) and isinstance(last, (int, float)):
        if isinstance(delta, (int, float)) and delta > 0:
            verb = "wzrósł"
        elif isinstance(delta, (int, float)) and delta < 0:
            verb = "spadł"
        else:
            return f"{label} — {zone}: bez zmiany, {_fmt(last)}{unit}."
        return f"{label} — {zone}: {verb} z {_fmt(first)}{unit} do {_fmt(last)}{unit}."

    return f"{label} — {zone}: wykryto zmianę w analizowanym oknie."


def _reading_headline(fact: dict[str, Any]) -> str:
    channel = str(fact.get("channel"))
    label = _CHANNEL_LABELS.get(channel, channel)
    delta = fact.get("delta")
    zone = _zone_label(fact.get("node_id"))
    if isinstance(delta, (int, float)) and delta > 0:
        return f"Wzrost {label} — {zone}"
    if isinstance(delta, (int, float)) and delta < 0:
        return f"Spadek {label} — {zone}"
    return f"Zmiana {label} — {zone}"


def _data_quality_short(packet: dict[str, Any]) -> str:
    window = packet.get("window", {})
    sample_count = window.get("sample_count") if isinstance(window, dict) else None
    sensor_bus = packet.get("sensor_bus", {})
    nodes = sensor_bus.get("nodes", {}) if isinstance(sensor_bus, dict) else {}
    missing_total = 0

    if isinstance(nodes, dict):
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
                    missing_total += int(missing)

    if missing_total:
        parts = ["Występują braki danych"]
    else:
        parts = ["Dane kompletne"]

    if isinstance(sample_count, int):
        parts.append(f"{sample_count} próbek")
    if missing_total:
        parts.append(f"{missing_total} brakujących odczytów")

    context = packet.get("analysis_context", {})
    if isinstance(context, dict) and context.get("historical_baseline_available") is False:
        parts.append("brak historycznego baseline'u")

    return " · ".join(parts)


def render_operator_view(
    packet: dict[str, Any],
    decision: Any,
    catalog: list[dict[str, Any]],
) -> VentilationOperatorView:
    """Build short deterministic HMI copy from the resolved v12 decision.

    The model has already selected grounded fact IDs. This formatter does not ask
    an LLM again and does not change status or recommendation policy.
    """

    by_id = {str(fact.get("id")): fact for fact in catalog}
    selected = [
        by_id[fact_id]
        for fact_id in getattr(decision, "selected_fact_ids", [])
        if fact_id in by_id
    ]
    status = str(getattr(decision, "status", "insufficient_data"))
    status_label = _STATUS_LABELS.get(status, "ANALIZA AI")

    alarms = [fact for fact in selected if fact.get("kind") == "active_alarm"]
    readings = [fact for fact in selected if fact.get("kind") == "reading"]
    health = [
        fact
        for fact in selected
        if fact.get("kind") in {"sensor_bus_health", "node_health"}
    ]

    if status == "anomaly" and alarms:
        codes = [str(fact.get("code")) for fact in alarms if fact.get("code")]
        headline = "Aktywny alarm systemu"
        summary = "CM5 zgłasza: " + ", ".join(codes) + "."
    elif status == "anomaly" and health:
        headline = "Problem techniczny systemu"
        summary = "Telemetria wskazuje problem komunikacji lub dostępności podsystemu pomiarowego."
    elif status == "attention" and readings:
        lead = readings[0]
        headline = _reading_headline(lead)
        summary_parts = [_reading_sentence(lead)]

        same_channel_other_zone = next(
            (
                fact
                for fact in readings[1:]
                if fact.get("channel") == lead.get("channel")
                and fact.get("node_id") != lead.get("node_id")
            ),
            None,
        )
        if same_channel_other_zone is not None:
            summary_parts.append(_reading_sentence(same_channel_other_zone))
        else:
            second = next(
                (
                    fact
                    for fact in readings[1:]
                    if fact.get("channel") != lead.get("channel")
                ),
                None,
            )
            if second is not None:
                summary_parts.append(_reading_sentence(second))
        summary = " ".join(summary_parts)
    elif status == "attention" and health:
        headline = "Jakość danych wymaga uwagi"
        summary = "W bieżącym oknie wystąpiła degradacja dostępności lub jakości danych pomiarowych."
    elif status == "attention":
        headline = "System wymaga uwagi"
        summary = "W bieżącym oknie wykryto zmianę wymagającą dalszej obserwacji."
    elif status == "no_anomaly_detected":
        headline = "Brak istotnych zmian"
        summary = "W bieżącym oknie nie wykryto zmian wymagających uwagi operatora."
    else:
        headline = "Za mało danych do analizy"
        summary = "Bieżące okno nie zawiera wystarczającej liczby próbek do wiarygodnej oceny."

    summary += _baseline_suffix(packet)

    recommendation_code = str(getattr(decision, "recommendation_code", "none"))
    if recommendation_code == "observe_next_windows":
        recommendation = "Obserwuj kolejne okna pomiarowe i sprawdź, czy trend się utrzymuje."
    elif recommendation_code == "diagnose_active_alarm":
        recommendation = "Sprawdź aktywne alarmy CM5 i wykonaj diagnostykę wskazanego podsystemu."
    else:
        recommendation = "Brak dodatkowych zaleceń dla tego okna."

    return VentilationOperatorView(
        status_label_pl=status_label,
        headline_pl=headline,
        summary_pl=summary,
        recommendation_pl=recommendation,
        data_quality_short_pl=_data_quality_short(packet),
    )


def render_insufficient_operator_view(
    *,
    sample_count: int,
    min_samples: int,
) -> VentilationOperatorView:
    return VentilationOperatorView(
        status_label_pl=_STATUS_LABELS["insufficient_data"],
        headline_pl="Za mało danych do analizy",
        summary_pl=(
            f"Bieżące okno zawiera {sample_count} próbek; wymagane minimum to {min_samples}."
        ),
        recommendation_pl="Poczekaj na pełniejsze okno telemetryczne.",
        data_quality_short_pl=f"Niepełne okno · {sample_count} próbek",
    )
