# AI Bridge – Ventilation AI Analysis Stage 2

**Data:** 10.08.2026  
**Status:** IMPLEMENTED – oczekuje na walidację na rzeczywistym Serwerze AI  
**Repozytorium:** `autoklinika/AI-server`  
**Gałąź:** `agent/ventilation-ai-analysis-stage2`

## 1. Cel

Dodać pierwszą rzeczywistą warstwę analizy przez lokalny model `qwen3.6:35b` po zakończeniu Stage 1 telemetry ingest.

Stage 2 ma wykonywać:

```text
RAW telemetry in PostgreSQL
        ↓
Python mathematical preparation
        ↓
ventilation domain prompt
        ↓
Ollama / Qwen
        ↓
validated structured advisory result
        ↓
PostgreSQL analysis history
```

Warstwa AI nie znajduje się na ścieżce sterowania i nie znajduje się na ścieżce ACK dla CM5.

## 2. Niezmieniona granica bezpieczeństwa

Nadal obowiązuje:

```text
CM5 = sterowanie + safety
AI Bridge = dane + infrastruktura analityczna
Python = matematyczne przygotowanie danych
Qwen = interpretacja + rekomendacje
```

AI nie wysyła komend do CM5.

Nie zmieniono endpointu ingest:

```text
POST /api/v1/ventilation/telemetry/batches
```

Nie dodano endpointów sterujących.

## 3. Nowe moduły

### `src/ai_bridge/analysis/`

Dodano wspólną warstwę uruchamiania analiz:

```text
analysis/
├── __init__.py
├── main.py
├── schemas.py
└── service.py
```

### `src/ai_bridge/adapters/ventilation/analysis.py`

Adapter domenowy przygotowuje matematyczne podsumowanie danych wentylacji oraz prompt dla Qwena.

### `src/ai_bridge/storage/analysis_repository.py`

Repozytorium odpowiada za:

- odczyt RAW dla określonego okna,
- wykrycie istniejącej analizy,
- zapis wyniku analizy.

### `src/ai_bridge/ollama/client.py`

Klient został rozszerzony z samego health/availability do rzeczywistego `POST /api/chat` z structured outputs.

## 4. Okno analizy

Domyślnie:

```text
15 minut
```

Okna są wyrównane do zegara:

```text
HH:00:00..HH:15:00
HH:15:00..HH:30:00
HH:30:00..HH:45:00
HH:45:00..HH+1:00:00
```

Zapytanie SQL używa:

```text
captured_at >= window_start
captured_at <  window_end
```

Dzięki temu próbka graniczna nie trafia do dwóch okien.

## 5. Matematyczne przygotowanie danych

Python nie decyduje, czy występuje anomalia.

Dla wartości liczbowych oblicza:

- count,
- missing,
- mean,
- min,
- max,
- stddev,
- first,
- last,
- delta,
- slope_per_minute.

Dla stanu systemu przygotowuje m.in.:

- rozkład trybów,
- statystyki zadanych napięć supply/extract,
- udział `hardware_ready=true`,
- udział `output_state_known=true`,
- maksymalny `consecutive_hardware_failures`,
- liczbę snapshotów z alarmem,
- listę kodów alarmów.

Dla SENSOR BUS przygotowuje:

- udział `ready=true`,
- udział `worker_alive=true`,
- maksymalną liczbę restartów workera,
- ostatni błąd,
- statystyki osobno dla każdego `slave_address`.

Dla każdego SEN55 agregowane są rzeczywiste pola:

```text
pm1_0_ug_m3
pm2_5_ug_m3
pm4_0_ug_m3
pm10_0_ug_m3
humidity_percent
temperature_celsius
voc_index
nox_index
```

oraz liczniki diagnostyczne:

```text
sensor_errors
modbus_service_errors
communication_errors
consecutive_failures
invalid_measurements
stale_measurements
map_version_errors
```

Python nie tworzy nazw typu „nawiew/wywiew” dla węzłów SEN55; zachowuje `slave_address`.

## 6. Data-quality gate

CM5 zapisuje snapshot co około 5 s.

Pełne 15 minut to około:

```text
180 próbek
```

Domyślne minimum Stage 2:

```text
120 próbek
```

Jeżeli próbek jest mniej:

- Qwen nie jest wywoływany,
- zapisujemy `status=insufficient_data`,
- zachowujemy podsumowanie danych i notę jakościową.

Jest to warunek jakości materiału wejściowego, nie próg anomalii.

## 7. Prompt domenowy

Prompt jawnie informuje Qwena, że:

- jego rola jest wyłącznie analityczna,
- CM5 jest jedynym sterownikiem,
- setpointy 0–10 V nie są pomiarem RPM ani rzeczywistego napięcia,
- system nie ma obecnie CO2, RPM/tacho ani przepływu,
- null/missing nie oznacza zera,
- nie wolno wymyślać baseline'u ani progów,
- nie wolno zakładać przyczynowości bez danych,
- rekomendacje są dla operatora.

Aktualna wersja promptu:

```text
ventilation-v1
```

Zmiana promptu powinna podnieść `PROMPT_VERSION`, dzięki czemu można świadomie analizować historyczne okna nową wersją bez naruszania idempotencji starego wyniku.

## 8. Structured outputs

Model jest wywoływany przez lokalne Ollama:

```text
POST http://127.0.0.1:11434/api/chat
```

Parametry:

```text
model       = qwen3.6:35b
stream      = false
think       = false
temperature = 0
format      = JSON Schema VentilationAnalysisResult
```

Odpowiedź jest ponownie walidowana przez Pydantic.

Nie zapisujemy pola `thinking` ani wewnętrznego toku rozumowania.

## 9. Wynik analizy

Model zwraca:

```text
schema_version
status
summary
confidence
observations[]
anomalies[]
recommendations[]
data_quality_notes[]
```

Status jest ograniczony do:

```text
normal
attention
anomaly
insufficient_data
```

Anomalie zawierają m.in. severity, evidence, probable_causes i confidence.

Rekomendacje zawierają priority, recommendation, rationale oraz flagę `operator_action_required`.

## 10. PostgreSQL – nowa tabela

Migracja:

```text
alembic/versions/0002_ventilation_analysis.py
```

Tworzy:

```text
ventilation_analysis_runs
```

Najważniejsze pola:

```text
analysis_id
source_id
window_start
window_end
created_at
model
prompt_version
sample_count
status
input_summary
result
raw_response
prompt_eval_count
eval_count
total_duration_ns
```

## 11. Idempotencja

Unikalność:

```text
(source_id, window_start, window_end, model, prompt_version)
```

Jeżeli analiza już istnieje, CLI zwraca zapisany wynik z:

```text
reused_existing=true
```

Qwen nie jest wtedy ponownie wywoływany.

## 12. CLI

Nowy entry point:

```text
ai-bridge-analyze-ventilation
```

Bez argumentów analizuje ostatnie zakończone wyrównane okno.

Można również podać ręcznie koniec okna:

```text
ai-bridge-analyze-ventilation --end-at 2026-08-10T12:30:00+00:00
```

## 13. Konfiguracja

Nowe ustawienia:

```text
AI_BRIDGE_OLLAMA_ANALYSIS_TIMEOUT_SECONDS=300
AI_BRIDGE_ANALYSIS_WINDOW_MINUTES=15
AI_BRIDGE_ANALYSIS_MIN_SAMPLES=120
AI_BRIDGE_ANALYSIS_THINK=false
AI_BRIDGE_ANALYSIS_TEMPERATURE=0
AI_BRIDGE_VENTILATION_SOURCE_ID=workshop-ventilation-cm5-01
```

`analysis_window_minutes` jest walidowane i musi dzielić 60.

## 14. systemd – przygotowane, jeszcze niewłączone

Dodano:

```text
deploy/systemd/ai-bridge-analysis.service
deploy/systemd/ai-bridge-analysis.timer
```

Timer:

```text
*-*-* *:00,15,30,45:30
```

Czyli 30 s po każdym zakończeniu kwartalnego okna.

Timer nie powinien zostać włączony przed ręczną walidacją na rzeczywistym Serwerze AI.

## 15. Relacja z działającym `ai-bridge.service`

Proces analityczny jest osobnym oneshotem.

Nie trzeba zatrzymywać działającego ingestu.

Podczas testów Stage 2 obecny produkcyjny:

```text
/opt/ai-bridge
ai-bridge.service
```

może nadal odbierać telemetrię Stage 1.

Gałąź Stage 2 może być testowana z:

```text
~/AI-server
```

na tej samej bazie i tej samej lokalnej Ollamie.

Migracja 0002 dodaje nową tabelę i jest wstecznie kompatybilna z procesem ingest Stage 1.

## 16. Testy dodane

Testy obejmują:

- wyrównanie okna 15-minutowego,
- walidację konfiguracji długości okna,
- poprawność podstawowej agregacji matematycznej,
- brak wywołania Ollamy przy insufficient data,
- reuse istniejącej analizy bez ponownego wywołania Qwena,
- kontrakt klienta Ollamy: `stream=false`, schema, `think=false`, temperature=0.

## 17. Elementy jeszcze niewalidowane

Przed uznaniem Stage 2 za PASS trzeba na rzeczywistym Serwerze AI wykonać:

1. `python -m compileall`,
2. pełny `pytest`,
3. `alembic upgrade head`,
4. ręczne `ai-bridge-analyze-ventilation`,
5. sprawdzenie wyniku Qwena,
6. potwierdzenie rekordu w `ventilation_analysis_runs`,
7. ponowienie tego samego okna i potwierdzenie `reused_existing=true`,
8. dopiero potem instalację i test timera systemd.

## 18. Znane ograniczenie

`Persistent=true` w timerze zapewnia uruchomienie po pominiętym triggerze, ale pojedynczy start analizuje tylko ostatnie zakończone okno. Pełny automatyczny backfill wielu kwartalnych okien po długiej awarii nie jest jeszcze zaimplementowany.

RAW pozostaje w PostgreSQL, więc żadne dane potrzebne do późniejszego backfillu nie giną.

## Wynik implementacji

**Stage 2 został zaimplementowany architektonicznie zgodnie z ADR-002/003/004 i nowym ADR-005. Nie jest jeszcze oznaczony jako operacyjnie zwalidowany, dopóki rzeczywisty Qwen nie przejdzie ręcznego testu na danych z CM5.**
