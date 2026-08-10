# AI Bridge – Ventilation AI Analysis Stage 2

**Data:** 10.08.2026  
**Status:** IMPLEMENTED – `ventilation-v7-compact-thinking` oczekuje na walidację jakościową  
**Repozytorium:** `autoklinika/AI-server`  
**Gałąź:** `agent/ventilation-ai-analysis-stage2`

## 1. Cel

Dodać rzeczywistą warstwę interpretacji danych wentylacji przez lokalny model `qwen3.6:35b`, bez naruszania granicy bezpieczeństwa CM5.

Aktywny tor:

```text
PostgreSQL RAW
    ↓
Python – pełne statystyki matematyczne
    ↓
pełny input_summary zapisany jako audit/history
    ↓
compact analysis packet
    ↓
krótki prompt domenowy
    ↓
Ollama / qwen3.6:35b / think=true
    ↓
prosty structured JSON
    ↓
Pydantic – walidacja struktury
    ↓
ventilation_analysis_runs
```

AI nie znajduje się na ścieżce sterowania ani ACK CM5.

## 2. Granica bezpieczeństwa

Nadal obowiązuje:

```text
CM5 = sterowanie + safety
Python = matematyka + przygotowanie danych
Qwen = interpretacja + rekomendacje
```

Nie ma endpointu sterującego. Awaria Qwena lub procesu analizy nie wpływa na wentylację ani na ingest telemetrii.

## 3. Okna i data-quality gate

Analiza działa na zamkniętych, wyrównanych oknach 15-minutowych:

```text
HH:00..HH:15
HH:15..HH:30
HH:30..HH:45
HH:45..HH+1:00
```

Domyślne minimum:

```text
120 próbek
```

Przy capture co około 5 s pełne okno ma około 180 próbek. Jeśli danych jest mniej, Qwen nie jest wywoływany i zapisywany jest `insufficient_data`.

## 4. Pełne przygotowanie matematyczne

Dla pól liczbowych Python oblicza:

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

Agregowane odczyty SEN55:

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

Dodatkowo przygotowywany jest stan systemu, setpointy, alarmy, SENSOR BUS, status obu węzłów i liczniki diagnostyczne.

Python nie definiuje progów anomalii i nie interpretuje tych wartości.

## 5. Structured output i Ollama

Aktywne wywołanie:

```text
POST http://127.0.0.1:11434/api/chat
model=qwen3.6:35b
stream=false
think=true
temperature=0
format=<compact JSON Schema>
```

Wynik pozostaje celowo prosty:

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

Pydantic sprawdza kontrakt danych, nie jakość semantyczną interpretacji.

## 6. Historia eksperymentów v1-v6

Wszystkie poniższe testy wykonywano na tym samym historycznym oknie:

```text
2026-08-10T12:00:00Z..12:15:00Z
179 próbek
```

### v1 – techniczny PASS, semantyczny FAIL

Model opisał PM jako `zero lub bliskie zeru`, mimo że PM2.5 wynosiło średnio około 6.9/6.6 µg/m³ i spadało na obu węzłach.

### v2 – semantyczny FAIL

Model poprawnie rozpoznał STOP i brak alarmów, ale pominął PM/VOC, nazwał dane statycznymi i wymyślił pseudo-ścieżki `sensor_data.*`.

### v3/v4 – zbyt rozbudowana walidacja

Dodano provenance i obowiązkowe pokrycie pól. Rzeczywiste requesty `HTTP 200` były następnie odrzucane głównie z powodu technicznego formularza odpowiedzi. Warstwa została wycofana.

### v5-simple – techniczny PASS, semantyczny FAIL

Po uproszczeniu schema i promptu przy `think=false` analiza została zapisana, ale model:

- praktycznie pominął PM/VOC,
- zwrócił puste observations,
- zinterpretował 0 V zbyt mocno jako potwierdzenie zatrzymania wentylatorów,
- ponownie sugerował diagnostykę STOP mimo braku informacji, czy STOP był zamierzony,
- zwrócił confidence=1.0 mimo braku baseline'u.

### v6-thinking – częściowa poprawa, nadal FAIL jakościowy

Zmiana wyłącznie `think=false -> think=true` dała zauważalną poprawę:

- Qwen zauważył lekki spadek PM,
- Qwen zauważył umiarkowany/silny wzrost VOC,
- poprawnie przypomniał, że 0–10 V to sygnały sterujące, nie RPM,
- jawnie wspomniał brak historycznego baseline'u.

Jednocześnie pojawiły się istotne błędy:

- model napisał `Brak pomiarów CO2 i wilgotności`, mimo że wilgotność była kompletna: 179/179 próbek na obu SEN55,
- zwrócił `status=anomaly`, ale `anomalies=[]`,
- confidence nadal było bardzo wysokie (`0.98`).

Wniosek: thinking pomaga w analizie trendów, ale pełny zagnieżdżony `input_summary` prawdopodobnie zawiera zbyt dużo równorzędnych szczegółów dla bieżącej interpretacji.

## 7. ventilation-v7-compact-thinking

`v7` zachowuje:

- ten sam model,
- `think=true`,
- `temperature=0`,
- ten sam krótki prompt domenowy co v6,
- ten sam prosty wynik JSON,
- brak semantycznych validatorów.

Zmienia się tylko materiał danych przekazywany Qwenowi.

### Pełny input_summary

Nadal jest obliczany i zapisywany do PostgreSQL jako materiał audytowy.

### Compact analysis packet

Nowy moduł:

```text
src/ai_bridge/adapters/ventilation/analysis_profile.py
```

buduje deterministyczny pakiet zawierający:

- window start/end/sample_count/capture_span,
- brak historycznego baseline'u,
- informację, że oczekiwany stan pracy nie jest znany,
- tryb sterownika, setpointy, readiness i alarmy,
- kondycję SENSOR BUS,
- oba SEN55,
- dla każdego parametru: count, missing, mean, min, max, delta, slope_per_minute,
- delty liczników diagnostycznych,
- listę rzeczywiście obecnych pomiarów,
- jawne `not_provided_by_system`: CO2, fan RPM, airflow.

Usuwane z materiału dla modelu są m.in.:

- stddev,
- first,
- last,
- pełne rekordy liczników,
- firmware_version,
- map_version,
- sequence,
- inne szczegóły niepotrzebne do bieżącej interpretacji.

To nie jest preprocessing decyzyjny. Python jedynie redukuje redundancję i eksponuje dostępność danych.

## 8. Szczególna ochrona przed błędem z v6

Compact packet zawiera oddzielnie:

```text
measurement_capabilities.present_in_packet
measurement_capabilities.not_provided_by_system
```

Dzięki temu `humidity_percent` jest jawnie obecne, jeśli ma próbki, natomiast CO2/RPM/airflow są jawnie oznaczone jako niewystępujące w systemie.

Nie oznacza to klasyfikacji jakości pomiaru; to wyłącznie informacja o dostępności danych.

## 9. PostgreSQL i idempotencja

Tabela:

```text
ventilation_analysis_runs
```

Unikalność:

```text
(source_id, window_start, window_end, model, prompt_version)
```

Aktywna wersja:

```text
ventilation-v7-compact-thinking
```

Dzięki nowej wersji to samo okno może zostać przeanalizowane ponownie bez usuwania historii v1-v6.

Pełny `input_summary` nadal trafia do rekordu analizy.

## 10. Walidacja techniczna wykonana dotychczas

Na rzeczywistym Serwerze AI potwierdzono:

- `compileall` PASS,
- kolejne pełne zestawy pytest PASS,
- Alembic `0002_ventilation_analysis` PASS,
- Ollama `/api/chat` HTTP 200,
- zapis analiz do PostgreSQL,
- idempotencję tego samego `(window, model, prompt_version)`,
- działanie `think=true`,
- poprawkę schema grammar,
- brak wpływu Qwena na ingest i CM5.

Timer systemd nadal pozostaje niewłączony.

## 11. Walidacja v7 do wykonania

Dla dokładnie tego samego okna 179 próbek należy sprawdzić:

1. pełny `pytest`,
2. realny `POST /api/chat`,
3. nowy `prompt_version=ventilation-v7-compact-thinking`,
4. czy Qwen poprawnie widzi PM i VOC,
5. czy poprawnie widzi humidity na obu węzłach,
6. czy nie twierdzi, że CO2 istnieje,
7. czy nie diagnozuje STOP bez podstawy,
8. czy status i `anomalies[]` są ze sobą logicznie spójne,
9. czy confidence odpowiada ograniczeniom braku baseline'u,
10. dopiero po jakościowym PASS przejść do testu timera systemd.

## 12. Status

Stage 2 pozostaje Draft. Nie oznaczać PR jako Ready i nie wykonywać merge przed ręcznym jakościowym PASS `ventilation-v7-compact-thinking` na rzeczywistym Serwerze AI.
