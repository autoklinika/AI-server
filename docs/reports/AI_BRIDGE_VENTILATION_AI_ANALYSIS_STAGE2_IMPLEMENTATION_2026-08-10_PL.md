# AI Bridge – Ventilation AI Analysis Stage 2

**Data:** 10.08.2026  
**Status:** IMPLEMENTED – `ventilation-v8-reporting` oczekuje na walidację jakościową  
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
krótki prompt domenowy/reportingowy
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

## 7. v7-compact-thinking – kierunek packetu potwierdzony

`ventilation-v7-compact-thinking` zachował:

- model `qwen3.6:35b`,
- `think=true`,
- `temperature=0`,
- prosty structured output,
- brak semantycznych validatorów.

Zmienił się tylko materiał wejściowy dla Qwena: zamiast pełnego zagnieżdżonego `input_summary` model otrzymał compact analysis packet.

Realny wynik dla tego samego okna 179 próbek:

```text
analysis_id=f53a4908-47c4-433a-9da6-80af670d0cf4
prompt_version=ventilation-v7-compact-thinking
reused_existing=false
status=normal
HTTP 200 OK
```

Qwen poprawnie zauważył:

- rosnący VOC (`+14.0`, około `+0.75/min` w cytowanym fragmencie),
- lekko spadające PM,
- stabilną temperaturę i wilgotność z niewielkimi zmianami,
- płaski NOx na poziomie 1.0.

Błąd z v6 dotyczący rzekomego braku wilgotności nie powtórzył się. Compact packet należy więc uznać za **PASS jako format wejścia**.

Pozostały problemy końcowego raportu:

- odpowiedź była po angielsku mimo instrukcji PL,
- `observations=[]` mimo prawidłowo zauważonych trendów,
- pojawił się meta-tekst `Ready to convert, plot, threshold-check, or integrate as needed`,
- użyto absolutnego sformułowania `Perfect data quality`,
- `confidence=0.98` pozostaje zbyt agresywne przy braku baseline'u.

Wniosek: nie zmieniamy już compact packetu. Problem jest raportowy.

## 8. ventilation-v8-reporting

Aktywny profil:

```text
ventilation-v8-reporting
```

`v8` zachowuje bez zmian:

- compact analysis packet z v7,
- model,
- `think=true`,
- `temperature=0`,
- flat schema,
- brak semantycznych validatorów.

Zmienia się wyłącznie instrukcja raportowania w promptcie.

Model ma teraz jawnie:

- odpowiadać tylko po polsku,
- umieszczać kluczowe fakty i trendy w `observations`, jeśli dane są wystarczające,
- nie dodawać meta-ofert typu `ready to plot`,
- nie nazywać jakości danych `perfect/idealną` bez podstaw,
- używać `status=anomaly` tylko z konkretną pozycją w `anomalies`,
- ograniczać confidence przy braku historycznego baseline'u,
- nie rekomendować diagnostyki STOP tylko dlatego, że system jest w STOP.

Są to zasady promptu, nie reguły walidatora Python.

## 9. Compact analysis packet

Moduł:

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

Pełny `input_summary` nadal jest zapisywany do PostgreSQL jako materiał audytowy.

## 10. PostgreSQL i idempotencja

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
ventilation-v8-reporting
```

Dzięki nowej wersji to samo okno może zostać przeanalizowane ponownie bez usuwania historii v1-v7.

## 11. Walidacja techniczna wykonana dotychczas

Na rzeczywistym Serwerze AI potwierdzono:

- `compileall` PASS,
- kolejne pełne zestawy pytest PASS,
- Alembic `0002_ventilation_analysis` PASS,
- Ollama `/api/chat` HTTP 200,
- zapis analiz do PostgreSQL,
- idempotencję tego samego `(window, model, prompt_version)`,
- działanie `think=true`,
- poprawkę schema grammar,
- brak wpływu Qwena na ingest i CM5,
- skuteczność compact analysis packet w v7.

Timer systemd nadal pozostaje niewłączony.

## 12. Walidacja v8 do wykonania

Dla dokładnie tego samego okna 179 próbek należy sprawdzić:

1. pełny `pytest`,
2. realny `POST /api/chat`,
3. `prompt_version=ventilation-v8-reporting`,
4. język polski,
5. niepuste i merytoryczne `observations`,
6. poprawne PM/VOC/humidity/temperature/NOx,
7. brak meta-ofert,
8. spójność `status` z `anomalies[]`,
9. rozsądne confidence przy braku baseline'u,
10. brak nieuprawnionej diagnostyki STOP,
11. dopiero po jakościowym PASS przejść do testu timera systemd.

## 13. Status

Stage 2 pozostaje Draft. Nie oznaczać PR jako Ready i nie wykonywać merge przed ręcznym jakościowym PASS `ventilation-v8-reporting` na rzeczywistym Serwerze AI.
