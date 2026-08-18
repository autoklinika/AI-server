# Ventilation Telemetry — rozszerzenie kontraktu aktualnego CoreState

Data: 2026-08-18

## Powód

Po wdrożeniu zintegrowanego `ventilation-core` na CM5 lokalny capture telemetrii działał, lecz AI Bridge odpowiadał HTTP 422. Pierwszym odrzuconym polem było `metrics.aero_bus`.

Przyczyną był drift kontraktu: AI Bridge nadal walidował historyczny `CoreState`, który obejmował tylko sterowanie DAC, alarmy i SENSOR BUS, podczas gdy aktualny autorytatywny `CoreState` CM5 zawiera również AERO, TACHO, Zigbee, harmonogram i SHADOW oraz rozszerzoną diagnostykę SEN55 i metadane alertów.

## Zasada architektoniczna

Źródłem prawdy pozostaje `ventilation-core` na CM5. AI Bridge nie tworzy alternatywnego modelu sterowania i nadal nie udostępnia żadnych endpointów sterujących.

## Zakres zmiany

Transport API pozostaje `schema_version = 1`. Jest to addytywne rozszerzenie pól już wdrożonego CoreState, a nie zmiana semantyki otoczki transportowej.

Silnie typowane pozostają dotychczasowe stabilne pola kontrolera i SENSOR BUS. Dodano:

- metadane alertów: `alert_id`, `source`, `acknowledged`, `acknowledged_at`,
- diagnostykę SEN55: flagi statusu urządzenia i `sen55_diagnostics_failures`,
- jawne top-level komponenty aktualnego CoreState: `aero_bus`, `tacho`, `zigbee`, `schedule`, `shadow_automation`.

Nowe komponenty są obecnie zachowywane jako obiekty JSON bez interpretacji po stronie ingest. Dzięki temu AI Bridge przyjmuje i przechowuje autorytatywny snapshot CM5, ale istniejący profil analityczny nie zostaje automatycznie rozszerzony o nowe wnioski ani progi.

Nieznane top-level pola `metrics` nadal są odrzucane (`extra=forbid`), więc przypadkowy drift poza jawnie obsługiwanym CoreState pozostaje wykrywalny.

## Bezpieczeństwo

Zmiana dotyczy wyłącznie ingest/storage. Nie dodaje endpointów sterujących, nie wysyła poleceń do CM5 i nie zmienia działania Qwena.

## Walidacja oczekiwana

1. pełny test suite AI-server,
2. test payloadu odpowiadającego zintegrowanemu CoreState,
3. wdrożenie na `/opt/ai-bridge`,
4. restart tylko `ai-bridge.service`,
5. potwierdzenie HTTP 200 dla batcha z CM5,
6. potwierdzenie zmniejszania lokalnego backlogu `pending_samples` na CM5.
