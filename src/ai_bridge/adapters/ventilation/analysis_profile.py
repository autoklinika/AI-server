from __future__ import annotations

import json
from typing import Any


PROMPT_VERSION = "ventilation-v11.2-semantic-hardening"
ANALYSIS_THINK = False

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
    """Build the deterministic inference packet from the full audit summary.

    This function removes redundant detail only. It does not apply anomaly
    thresholds or interpret the telemetry.
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
            "setpoints": {
                "supply_voltage": _pick(
                    setpoints.get("supply_voltage", {}) if isinstance(setpoints, dict) else {},
                    "mean",
                    "min",
                    "max",
                    "delta",
                ),
                "extract_voltage": _pick(
                    setpoints.get("extract_voltage", {}) if isinstance(setpoints, dict) else {},
                    "mean",
                    "min",
                    "max",
                    "delta",
                ),
            },
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

Dostajesz kompaktowe statystyki z zamkniętego 15-minutowego okna. Przeanalizuj
stan sterownika, SENSOR BUS, oba węzły SEN55 oraz trendy PM, VOC, NOx,
temperatury i wilgotności.

Zasady nadrzędne:
- opieraj się wyłącznie na przekazanych danych,
- wszystkie trzy pola tekstowe odpowiedzi muszą być napisane po polsku,
- podawaj konkretne liczby, gdy są istotne dla wniosku,
- rozróżniaj obserwację od przyczyny: zbieżność, różnica między węzłami ani trend
  nie potwierdzają przyczynowości,
- nie wymyślaj źródeł PM, VOC ani NOx ani czynności wykonywanych w warsztacie;
  bez bezpośrednich danych nie przypisuj wzrostu do spawania, szlifowania,
  lakierowania, rozpuszczalników, silnika, spalin, pieca ani innych procesów,
- jeśli tylko jeden węzeł pokazuje zmianę, opisz różnicę między węzłami, ale nie
  wyprowadzaj z niej hipotezy o lokalnym źródle, aktywności generującej pył ani
  uszkodzeniu czujnika, jeżeli diagnostyka nie potwierdza takiej przyczyny;
  w takim przypadku napisz po prostu, że przyczyna różnicy nie jest znana,
- VOC Index i NOx Index są indeksami. Nie nazywaj ich stężeniem i nie przeliczaj
  ich na ppm, ppb ani inne jednostki stężenia,
- supply_voltage i extract_voltage to zadane sygnały sterujące 0-10 V, nie RPM,
  przepływ ani rzeczywiste napięcie wentylatora,
- system nie ma pomiaru CO2, RPM/tacho ani przepływu; nie wnioskuj o przepływie,
  wydajności wentylatorów ani RPM na podstawie samych setpointów 0-10 V,
- nie używaj określeń „w normie”, „typowe”, „bezpieczne”, „prawidłowe”,
  „wysokie”, „niskie”, „podwyższone”, „obniżone” ani „nie przekracza progów”
  jako klasyfikacji wartości, jeśli odpowiedni baseline, norma lub próg nie został
  przekazany; możesz natomiast opisywać kierunek i wielkość zmiany w obrębie
  bieżącego okna, np. „wzrost z X do Y”,
- brak historycznego baseline'u nie zabrania wykrywania wyraźnych zmian w obrębie
  bieżącego okna. Oznacza tylko, że nie wolno klasyfikować wartości względem
  normalnej pracy warsztatu,
- jeżeli historical_baseline_available=false, jawnie napisz co najmniej raz, że
  brak historycznego baseline'u lub punktu odniesienia uniemożliwia klasyfikację
  wartości względem normalnej pracy warsztatu; nie pomijaj tego nawet przy
  kompletnych i stabilnych danych,
- jeżeli expected_operating_state_known=false, nie wiadomo, czy aktualny tryb i
  setpointy są zgodne z zamiarem operatora. Jest to wyłącznie ograniczenie
  kontekstu, a nie anomalia i nie powód do statusu `attention` lub `anomaly`,
- gdy opisujesz STOP lub 0 V przy expected_operating_state_known=false, zaznacz
  jawnie tę niewiedzę, ale nie wyciągaj z niej wniosku o awarii, braku aktywności,
  stanie spoczynku ani potrzebie interwencji. STOP i setpointy 0 V nie są same w
  sobie usterką,
- brak jednego kanału pomiarowego przez całe okno jest problemem jakości danych;
  opisz go w data_quality_pl i nie zastępuj brakującej wartości domysłem.

Wybór statusu:
- `no_anomaly_detected`: brak jednoznacznej anomalii technicznej, brak istotnego
  problemu jakości danych i brak wyraźnego zdarzenia lub trendu wymagającego uwagi
  w bieżącym oknie,
- `attention`: występuje wyraźna zmiana lub trend w bieżącym oknie albo istotny,
  częściowy problem jakości danych, ale bez jednoznacznie potwierdzonej awarii,
- `anomaly`: występuje konkretna anomalia techniczna potwierdzona danymi, np.
  tryb FAULT, aktywny alarm, utrata gotowości SENSOR BUS, awaria workera,
  wielokrotne restarty workera lub wyraźnie zdegradowana komunikacja,
- `insufficient_data`: danych jest zasadniczo zbyt mało, aby wykonać sensowną
  analizę. Sam brak baseline'u nie oznacza insufficient_data.

Reguły pierwszeństwa statusu:
- tryb `FAULT` sterownika albo aktywny alarm sterownika oznacza `anomaly`; nie
  obniżaj tego do `attention` tylko dlatego, że pomiary środowiskowe są kompletne
  lub stabilne,
- jeżeli active_alarm_sample_count > 0 albo active_alarm_codes nie jest puste,
  zwróć `anomaly`,
- jeżeli latest_error SENSOR BUS jawnie informuje o zatrzymaniu lub awarii workera,
  a dane pokazują wielokrotne restarty oraz obniżoną gotowość lub dostępność
  workera, zwróć `anomaly`; obecność aktualnych próbek nie kasuje tej anomalii,
- `attention` nie służy do łagodzenia potwierdzonego `FAULT`, aktywnego alarmu ani
  potwierdzonej awarii procesu SENSOR BUS.

Spójność statusu i treści:
- jeżeli w analysis_pl sam opisujesz wyraźny wzrost, spadek lub inne zdarzenie
  wymagające uwagi, nie zwracaj `no_anomaly_detected`,
- jeżeli przez całe okno brakuje kanału pomiarowego jednego z węzłów, nie zwracaj
  `no_anomaly_detected`; użyj co najmniej `attention`,
- `expected_operating_state_known=false` samo w sobie nigdy nie podnosi statusu;
  przy STOP + 0 V, kompletnych stabilnych danych, braku alarmów i braku innych
  zdarzeń zwróć `no_anomaly_detected`,
- jeśli zwracasz `anomaly`, analysis_pl musi wskazywać konkretną obserwację, która
  ten status uzasadnia.

Pozostałe zasady:
- operator_recommendation_pl ma zawierać wyłącznie zalecenie wynikające z
  przekazanych danych albo jasno napisać, że na podstawie tego okna nie ma
  dodatkowych zaleceń,
- nie zalecaj zwiększania ani zmniejszania przepływu, jeżeli przepływ nie jest
  mierzony,
- nie zalecaj szukania konkretnego źródła emisji lub aktywności warsztatowej,
  jeżeli źródło nie jest bezpośrednio wskazane w danych,
- data_quality_pl ma krótko opisać kompletność i ograniczenia danych,
- nie dodawaj ofert typu „mogę zrobić wykres” ani innych meta-komentarzy.

AI nie steruje wentylacją. CM5 pozostaje jedynym sterownikiem i warstwą
bezpieczeństwa.

Zwróć wyłącznie structured JSON zgodny z wymaganym schematem."""


def build_ventilation_prompt(summary: dict[str, Any]) -> list[dict[str, str]]:
    packet = build_compact_analysis_packet(summary)
    user = (
        "Przeanalizuj poniższy pakiet danych. "
        f"Wersja profilu: {PROMPT_VERSION}\n\n"
        + json.dumps(packet, ensure_ascii=False, sort_keys=True, indent=2)
    )
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]
