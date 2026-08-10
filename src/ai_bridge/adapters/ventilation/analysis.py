from __future__ import annotations

from collections import Counter
from datetime import datetime
import json
import math
from statistics import fmean, pstdev
from typing import Any, Iterable

from ai_bridge.adapters.ventilation.schemas import VentilationMetrics
from ai_bridge.storage.models import TelemetrySampleRecord


PROMPT_VERSION = "ventilation-v1"

READING_FIELDS = (
    "pm1_0_ug_m3",
    "pm2_5_ug_m3",
    "pm4_0_ug_m3",
    "pm10_0_ug_m3",
    "humidity_percent",
    "temperature_celsius",
    "voc_index",
    "nox_index",
)

COUNTER_FIELDS = (
    "sensor_errors",
    "modbus_service_errors",
    "communication_errors",
    "consecutive_failures",
    "invalid_measurements",
    "stale_measurements",
    "map_version_errors",
)


def _round(value: float | None, digits: int = 4) -> float | None:
    return None if value is None else round(value, digits)


def _numeric_summary(
    points: list[tuple[datetime, float]],
    *,
    expected_count: int,
) -> dict[str, Any]:
    if not points:
        return {
            "count": 0,
            "missing": expected_count,
            "mean": None,
            "min": None,
            "max": None,
            "stddev": None,
            "first": None,
            "last": None,
            "delta": None,
            "slope_per_minute": None,
        }

    points = sorted(points, key=lambda item: item[0])
    values = [value for _, value in points]
    first = values[0]
    last = values[-1]

    slope: float | None
    if len(points) < 2:
        slope = 0.0
    else:
        origin = points[0][0]
        xs = [(ts - origin).total_seconds() / 60.0 for ts, _ in points]
        x_mean = fmean(xs)
        y_mean = fmean(values)
        denominator = sum((x - x_mean) ** 2 for x in xs)
        if math.isclose(denominator, 0.0):
            slope = 0.0
        else:
            slope = sum(
                (x - x_mean) * (y - y_mean)
                for x, y in zip(xs, values, strict=True)
            ) / denominator

    return {
        "count": len(values),
        "missing": max(0, expected_count - len(values)),
        "mean": _round(fmean(values)),
        "min": _round(min(values)),
        "max": _round(max(values)),
        "stddev": _round(pstdev(values) if len(values) > 1 else 0.0),
        "first": _round(first),
        "last": _round(last),
        "delta": _round(last - first),
        "slope_per_minute": _round(slope),
    }


def _counter_summary(values: list[int]) -> dict[str, int | None]:
    if not values:
        return {"first": None, "last": None, "delta": None, "max": None}
    return {
        "first": values[0],
        "last": values[-1],
        "delta": values[-1] - values[0],
        "max": max(values),
    }


def _ratio_true(values: Iterable[bool]) -> float | None:
    materialized = list(values)
    if not materialized:
        return None
    return round(sum(1 for value in materialized if value) / len(materialized), 4)


def summarize_ventilation_window(
    *,
    source_id: str,
    window_start: datetime,
    window_end: datetime,
    samples: list[TelemetrySampleRecord],
) -> dict[str, Any]:
    parsed: list[tuple[TelemetrySampleRecord, VentilationMetrics]] = [
        (sample, VentilationMetrics.model_validate(sample.metrics))
        for sample in samples
    ]

    modes = Counter(metrics.mode for _, metrics in parsed)
    setpoint_supply = [
        (sample.captured_at, metrics.setpoints.supply_voltage)
        for sample, metrics in parsed
    ]
    setpoint_extract = [
        (sample.captured_at, metrics.setpoints.extract_voltage)
        for sample, metrics in parsed
    ]

    alarm_codes = sorted(
        {
            alarm.code
            for _, metrics in parsed
            for alarm in metrics.active_alarms
        }
    )
    alarm_sample_count = sum(
        1 for _, metrics in parsed if metrics.active_alarms
    )

    bus_pairs = [
        (sample, metrics.sensor_bus)
        for sample, metrics in parsed
        if metrics.sensor_bus is not None
    ]

    node_addresses = sorted(
        {
            node.slave_address
            for _, bus in bus_pairs
            for node in bus.nodes
        }
    )

    nodes: dict[str, Any] = {}
    for address in node_addresses:
        node_points = []
        for sample, bus in bus_pairs:
            matching = next(
                (node for node in bus.nodes if node.slave_address == address),
                None,
            )
            if matching is not None:
                node_points.append((sample, matching))

        reading_summaries: dict[str, Any] = {}
        for field in READING_FIELDS:
            points: list[tuple[datetime, float]] = []
            for sample, node in node_points:
                value = getattr(node.reading, field)
                if value is not None:
                    points.append((sample.captured_at, float(value)))
            reading_summaries[field] = _numeric_summary(
                points,
                expected_count=len(node_points),
            )

        counter_summaries = {
            field: _counter_summary(
                [int(getattr(node, field)) for _, node in node_points]
            )
            for field in COUNTER_FIELDS
        }

        latest_node = node_points[-1][1] if node_points else None
        nodes[str(address)] = {
            "samples_present": len(node_points),
            "online_true_ratio": _ratio_true(
                node.online for _, node in node_points
            ),
            "usable_true_ratio": _ratio_true(
                node.usable for _, node in node_points
            ),
            "measurement_valid_true_ratio": _ratio_true(
                node.measurement_valid for _, node in node_points
            ),
            "measurement_stale_true_ratio": _ratio_true(
                node.measurement_stale for _, node in node_points
            ),
            "sensor_present_true_ratio": _ratio_true(
                node.sensor_present for _, node in node_points
            ),
            "readings": reading_summaries,
            "counters": counter_summaries,
            "latest": None
            if latest_node is None
            else {
                "age_seconds": latest_node.age_seconds,
                "firmware_version": latest_node.firmware_version,
                "map_version": latest_node.map_version,
                "sequence": latest_node.sequence,
                "last_error": latest_node.last_error,
            },
        }

    captured_times = [sample.captured_at for sample, _ in parsed]
    summary: dict[str, Any] = {
        "schema_version": 1,
        "domain": "ventilation",
        "source_id": source_id,
        "window": {
            "start": window_start.isoformat(),
            "end": window_end.isoformat(),
            "sample_count": len(parsed),
            "first_sample_at": None
            if not captured_times
            else min(captured_times).isoformat(),
            "last_sample_at": None
            if not captured_times
            else max(captured_times).isoformat(),
            "capture_span_seconds": None
            if len(captured_times) < 2
            else round(
                (max(captured_times) - min(captured_times)).total_seconds(),
                3,
            ),
        },
        "system": {
            "mode_counts": dict(sorted(modes.items())),
            "latest_mode": None if not parsed else parsed[-1][1].mode,
            "setpoints": {
                "supply_voltage": _numeric_summary(
                    setpoint_supply,
                    expected_count=len(parsed),
                ),
                "extract_voltage": _numeric_summary(
                    setpoint_extract,
                    expected_count=len(parsed),
                ),
            },
            "hardware_ready_true_ratio": _ratio_true(
                metrics.hardware_ready for _, metrics in parsed
            ),
            "output_state_known_true_ratio": _ratio_true(
                metrics.output_state_known for _, metrics in parsed
            ),
            "consecutive_hardware_failures_max": max(
                (metrics.consecutive_hardware_failures for _, metrics in parsed),
                default=0,
            ),
            "active_alarm_sample_count": alarm_sample_count,
            "active_alarm_codes": alarm_codes,
        },
        "sensor_bus": {
            "samples_present": len(bus_pairs),
            "ready_true_ratio": _ratio_true(bus.ready for _, bus in bus_pairs),
            "worker_alive_true_ratio": _ratio_true(
                bus.worker_alive for _, bus in bus_pairs
            ),
            "worker_restarts_max": max(
                (bus.worker_restarts for _, bus in bus_pairs),
                default=0,
            ),
            "latest_error": None if not bus_pairs else bus_pairs[-1][1].last_error,
            "nodes": nodes,
        },
    }
    return summary


def build_ventilation_prompt(summary: dict[str, Any]) -> list[dict[str, str]]:
    system = """Jesteś lokalnym analitykiem systemu wentylacji warsztatu.

Twoja rola jest wyłącznie analityczna i doradcza. Nigdy nie wydajesz komend
sterujących do CM5, nie ustawiasz napięć, trybów ani wyjść. CM5 jest jedynym
sterownikiem i jedyną warstwą bezpieczeństwa.

Otrzymujesz matematycznie przygotowane statystyki z okna czasowego. Interpretuj
wyłącznie dane, które rzeczywiście są obecne. Nie wymyślaj brakujących pomiarów,
progów ani baseline'u. Jeżeli nie ma jeszcze wiarygodnego baseline'u historycznego,
napisz to jawnie.

Ważne znaczenie danych:
- supply_voltage i extract_voltage są wartościami zadanymi 0-10 V, a nie pomiarem
  napięcia, przepływu ani RPM,
- system obecnie nie posiada pomiaru CO2, RPM/tacho ani przepływu powietrza,
- dwa węzły SENSOR BUS są identyfikowane przez slave_address; nie nadawaj im
  wymyślonych nazw fizycznych,
- null/missing oznacza brak danych, nigdy zero,
- Python policzył wyłącznie statystyki matematyczne. To Ty interpretujesz,
  czy występuje anomalia i jakie mogą być jej przyczyny.

Analizuj między innymi:
- spójność pomiarów pomiędzy węzłami,
- trendy, rozrzut, minima/maksima i zmiany w czasie,
- kondycję SENSOR BUS i jakość danych,
- relację stanu systemu i zadanych napięć do obserwowanych zmian jakości powietrza,
  ale nie zakładaj związku przyczynowego bez wystarczających danych,
- możliwe anomalie, ich prawdopodobne przyczyny i poziom pewności.

Rekomendacje są przeznaczone dla operatora i mogą dotyczyć diagnostyki,
obserwacji lub ręcznej decyzji człowieka. Nie formułuj ich jako automatycznych
poleceń dla sterownika.

Odpowiedz po polsku i dokładnie zgodnie z przekazanym JSON Schema."""

    user = (
        "Przeanalizuj poniższe statystyki okna telemetrycznego. "
        f"Wersja promptu: {PROMPT_VERSION}\n\n"
        + json.dumps(summary, ensure_ascii=False, sort_keys=True, indent=2)
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
