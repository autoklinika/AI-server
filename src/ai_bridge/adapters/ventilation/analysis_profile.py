from __future__ import annotations

import json
from typing import Any


PROMPT_VERSION = "ventilation-v7-compact-thinking"
ANALYSIS_THINK = True

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


def _pick(mapping: dict[str, Any] | None, *keys: str) -> dict[str, Any]:
    source = mapping or {}
    return {key: source.get(key) for key in keys}


def _compact_numeric(summary: dict[str, Any] | None) -> dict[str, Any]:
    return _pick(
        summary,
        "count",
        "missing",
        "mean",
        "min",
        "max",
        "delta",
        "slope_per_minute",
    )


def build_compact_analysis_packet(summary: dict[str, Any]) -> dict[str, Any]:
    """Build a concise deterministic packet for Qwen from the full input_summary.

    The full mathematical input_summary remains the audit/storage record. This
    packet only removes redundant/noisy fields before inference; it does not add
    anomaly thresholds or interpret the measurements.
    """

    context = summary.get("analysis_context", {})
    window = summary.get("window", {})
    system = summary.get("system", {})
    sensor_bus = summary.get("sensor_bus", {})
    raw_nodes = sensor_bus.get("nodes", {})

    nodes: dict[str, Any] = {}
    measurements_present: set[str] = set()

    if isinstance(raw_nodes, dict):
        for address, node_value in raw_nodes.items():
            node = node_value if isinstance(node_value, dict) else {}
            raw_readings = node.get("readings", {})
            readings: dict[str, Any] = {}
            for field in READING_FIELDS:
                metric = raw_readings.get(field, {}) if isinstance(raw_readings, dict) else {}
                compact = _compact_numeric(metric if isinstance(metric, dict) else {})
                readings[field] = compact
                if compact.get("count", 0):
                    measurements_present.add(field)

            raw_counters = node.get("counters", {})
            counter_deltas = {
                field: (
                    raw_counters.get(field, {}).get("delta")
                    if isinstance(raw_counters, dict)
                    and isinstance(raw_counters.get(field), dict)
                    else None
                )
                for field in COUNTER_FIELDS
            }

            nodes[str(address)] = {
                "samples_present": node.get("samples_present"),
                "online_ratio": node.get("online_true_ratio"),
                "measurement_valid_ratio": node.get("measurement_valid_true_ratio"),
                "measurement_stale_ratio": node.get("measurement_stale_true_ratio"),
                "sensor_present_ratio": node.get("sensor_present_true_ratio"),
                "readings": readings,
                "diagnostic_counter_deltas": counter_deltas,
                "latest_error": (
                    node.get("latest", {}).get("last_error")
                    if isinstance(node.get("latest"), dict)
                    else None
                ),
            }

    setpoints = system.get("setpoints", {})

    return {
        "schema_version": 1,
        "source_id": summary.get("source_id"),
        "window": _pick(
            window if isinstance(window, dict) else {},
            "start",
            "end",
            "sample_count",
            "capture_span_seconds",
        ),
        "analysis_context": {
            "historical_baseline_available": context.get("historical_baseline_available"),
            "expected_operating_state_known": context.get("expected_operating_state_known"),
        },
        "measurement_capabilities": {
            "present_in_packet": sorted(measurements_present),
            "not_provided_by_system": ["co2", "fan_rpm", "airflow"],
        },
        "controller": {
            "latest_mode": system.get("latest_mode"),
            "mode_counts": system.get("mode_counts", {}),
            "supply_setpoint_v": _pick(
                setpoints.get("supply_voltage", {}) if isinstance(setpoints, dict) else {},
                "mean",
                "min",
                "max",
                "delta",
            ),
            "extract_setpoint_v": _pick(
                setpoints.get("extract_voltage", {}) if isinstance(setpoints, dict) else {},
                "mean",
                "min",
                "max",
                "delta",
            ),
            "hardware_ready_ratio": system.get("hardware_ready_true_ratio"),
            "output_state_known_ratio": system.get("output_state_known_true_ratio"),
            "consecutive_hardware_failures_max": system.get(
                "consecutive_hardware_failures_max"
            ),
            "active_alarm_sample_count": system.get("active_alarm_sample_count"),
            "active_alarm_codes": system.get("active_alarm_codes", []),
        },
        "sensor_bus": {
            "ready_ratio": sensor_bus.get("ready_true_ratio"),
            "worker_alive_ratio": sensor_bus.get("worker_alive_true_ratio"),
            "worker_restarts_max": sensor_bus.get("worker_restarts_max"),
            "latest_error": sensor_bus.get("latest_error"),
            "nodes": nodes,
        },
    }


SYSTEM_PROMPT = """Jesteś lokalnym analitykiem systemu wentylacji warsztatu.

Dostajesz matematycznie przygotowane statystyki z zamkniętego 15-minutowego
okna. Przeanalizuj je jak inżynier obserwujący rzeczywisty system.

Zwróć uwagę na:
- stan sterownika i kondycję SENSOR BUS,
- oba węzły SEN55 osobno i ich wzajemną zgodność,
- PM, VOC, NOx, temperaturę i wilgotność,
- średnie, minima, maksima, zmiany i trendy w czasie,
- możliwe anomalie, nietypowe zachowania i rzeczy warte dalszej obserwacji.

Opieraj wnioski wyłącznie na przekazanych danych i podawaj istotne wartości
liczbowe w observations lub anomalies, gdy pomagają uzasadnić wniosek.

Ważny kontekst:
- supply_voltage i extract_voltage są zadanymi sygnałami sterującymi 0-10 V,
  a nie pomiarem RPM, przepływu ani rzeczywistego napięcia wentylatora,
- system nie ma obecnie pomiaru CO2, RPM/tacho ani przepływu powietrza,
- null/missing oznacza brak danych, nie zero,
- historyczny baseline warsztatu nie jest jeszcze dostępny, więc nie nazywaj
  wartości absolutnie normalnymi lub nienormalnymi względem historii obiektu;
  możesz natomiast oceniać zachowanie i trendy w tym oknie,
- nie wiadomo, czy system miał w tym okresie pracować. Tryb STOP i setpointy 0 V
  same w sobie nie oznaczają usterki,
- dwa sensory identyfikuj przez slave_address; nie wymyślaj ich fizycznych nazw.

Twoja rola jest wyłącznie analityczna i doradcza. Nie wydajesz komend sterujących,
nie zmieniasz trybów ani setpointów. CM5 pozostaje jedynym sterownikiem i warstwą
bezpieczeństwa.

Odpowiedz po polsku, zwięźle i konkretnie, zgodnie z wymaganym structured JSON."""


def build_ventilation_prompt(summary: dict[str, Any]) -> list[dict[str, str]]:
    packet = build_compact_analysis_packet(summary)
    user = (
        "Przeanalizuj poniższy kompaktowy pakiet statystyk okna telemetrycznego. "
        f"Wersja promptu: {PROMPT_VERSION}\n\n"
        + json.dumps(packet, ensure_ascii=False, sort_keys=True, indent=2)
    )
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]
