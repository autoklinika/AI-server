# AI Bridge – Ventilation AI Analysis Stage 2

**Data:** 10.08.2026  
**Status:** IMPLEMENTED – `ventilation-v5-simple` oczekuje na walidację jakościową  
**Repozytorium:** `autoklinika/AI-server`  
**Gałąź:** `agent/ventilation-ai-analysis-stage2`

## 1. Cel

Dodać pierwszą rzeczywistą warstwę interpretacji danych wentylacji przez lokalny model `qwen3.6:35b` po zakończeniu Stage 1 telemetry ingest.

```text
PostgreSQL RAW
    ↓
Python – matematyczne przygotowanie danych
    ↓
15-minutowe zamknięte okno
    ↓
Ollama / qwen3.6:35b
    ↓
prosty structured JSON
    ↓
Pydantic – walidacja struktury
    ↓
ventilation_analysis_runs
```

AI nie znajduje się na ścieżce sterowania ani na ścieżce ACK CM5.

## 2. Granica bezpieczeństwa

Nadal obowiązuje:

```text
CM5 = sterowanie + safety
Python = przygotowanie matematyczne i infrastruktura
Qwen = interpretacja + rekomendacje
```

Nie dodano endpointów sterujących. Awaria Qwena lub całego procesu analizy nie wpływa na działanie wentylacji ani na przyjmowanie telemetrii.

## 3. Okna i data-quality gate

Analiza działa na zamkniętych, wyrównanych oknach 15-minutowych:

```text
HH:00..HH:15
HH:15..HH:30
HH:30..HH:45
HH:45..HH+1:00
```

Warunek minimalny:

```text
120 próbek
```

Przy capture około 5 s pełne okno zawiera około 180 próbek. Jeśli próbek jest mniej, Qwen nie jest wywoływany i zapisywany jest `insufficient_data`.

## 4. Matematyka wykonywana przez Python

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

Dla systemu i SENSOR BUS przygotowuje m.in. rozkład trybów, setpointy, stan hardware, alarmy, kondycję workera i statystyki obu węzłów SEN55.

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

Python nie klasyfikuje tych wartości jako normalnych/anormalnych i nie definiuje progów środowiskowych.

## 5. Ollama

Wywołanie:

```text
POST http://127.0.0.1:11434/api/chat
```

Parametry:

```text
model=qwen3.6:35b
stream=false
think=false
temperature=0
format=<JSON Schema>
```

Klient używa grammar-friendly schema. Wcześniej rzeczywista Ollama ujawniła błąd `failed to parse grammar` dla rozbudowanego schematu Pydantic; dlatego istnieje funkcja kompaktująca schema. Pełna walidacja końcowego wyniku nadal odbywa się przez Pydantic.

## 6. Aktywny wynik – `ventilation-v5-simple`

Po rzeczywistych testach wcześniejszych promptów celowo uproszczono kontrakt.

Aktualny wynik:

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

`observations`, `anomalies`, `recommendations` i `data_quality_notes` są prostymi listami tekstów.

Pydantic sprawdza tylko:

- strukturę JSON,
- dozwolony status,
- typy pól,
- `confidence` w zakresie 0..1,
- podstawowe limity długości/list.

Nie sprawdza semantycznie, czy Qwen „wystarczająco dobrze” przeanalizował dane.

## 7. Aktywny prompt – `ventilation-v5-simple`

Prompt jest krótki i domenowy. Model ma:

- przeanalizować stan sterownika i SENSOR BUS,
- przeanalizować oba SEN55,
- zwrócić uwagę na PM, VOC, NOx, temperaturę i wilgotność,
- analizować średnie, minima, maksima, zmiany i trendy,
- porównywać oba węzły,
- podawać istotne liczby, gdy pomagają uzasadnić wniosek,
- nie wymyślać danych ani historycznego baseline'u,
- nie traktować STOP + setpoint 0 V jako usterki, ponieważ oczekiwany stan pracy nie jest znany,
- pamiętać, że setpointy są wartościami zadanymi, nie pomiarem RPM/przepływu,
- wyłącznie doradzać operatorowi.

Pełny JSON Schema nie jest już kopiowany do treści promptu; schema trafia do Ollamy przez `format`.

## 8. Historia walidacji v1-v4

Walidacja na rzeczywistym oknie 179 próbek pokazała:

### `ventilation-v1`

Technicznie PASS, semantycznie FAIL. Model błędnie opisał PM jako `zero lub bliskie zeru` i pominął rzeczywiste trendy.

### `ventilation-v2`

Model poprawnie rozpoznał STOP i brak alarmów, ale nadal pominął trendy PM/VOC, nazwał dane statycznymi i wymyślił pseudo-ścieżki `sensor_data.*`.

### `ventilation-v3/v4`

Dodano provenance, wymagane ścieżki i obowiązkowe pokrycie pól. Mechanizm zaczął jednak sprawdzać przede wszystkim zdolność Qwena do wypełniania technicznego formularza. Rzeczywiste requesty `HTTP 200` były odrzucane przez walidatory mimo poprawnego transportu i struktury.

Wniosek projektowy: wracamy do pierwotnej zasady projektu. Python przygotowuje matematykę. Qwen interpretuje. Pydantic pilnuje kontraktu danych, a jakość interpretacji jest oceniana na rzeczywistych wynikach, nie przez rozbudowany semantyczny walidator.

Kod i testy provenance zostały usunięte z aktywnej implementacji.

## 9. PostgreSQL i idempotencja

Tabela:

```text
ventilation_analysis_runs
```

Unikalność:

```text
(source_id, window_start, window_end, model, prompt_version)
```

Zmiana `prompt_version` pozwala analizować to samo historyczne okno nową wersją bez usuwania starszych wyników.

W tabeli zapisywane są m.in. `input_summary`, wynik modelu, raw response oraz metryki tokenów/czasu.

## 10. Walidacja wykonana dotychczas

Na rzeczywistym Serwerze AI wykonano:

- `compileall` – PASS,
- zestawy testów 17/17, 19/19, 21/21, 22/22 i 27/27 – PASS,
- migrację Alembic `0002_ventilation_analysis` – PASS,
- rzeczywisty request do Ollamy – `HTTP 200 OK`,
- zapis pierwszej analizy do PostgreSQL – PASS,
- idempotencję tego samego okna – PASS (`reused_existing=true` bez drugiego requestu do Qwena),
- walidację błędów schema/grammar – naprawione.

Pierwszy technicznie poprawny przebieg na 179 próbkach zużył 4457 tokenów promptu, 205 tokenów odpowiedzi i trwał 28.901 s.

`ventilation-v3` oraz `ventilation-v4` wykonały realne requesty `HTTP 200`, ale ich wyniki zostały odrzucone przez zbyt rygorystyczne kontrakty przed zapisem. Była to bezpośrednia przyczyna decyzji o `ventilation-v5-simple`.

## 11. systemd

Przygotowane są:

```text
deploy/systemd/ai-bridge-analysis.service
deploy/systemd/ai-bridge-analysis.timer
```

Timer planowany jest 30 s po każdym kwartale. Nadal nie należy go włączać przed jakościowym PASS `ventilation-v5-simple`.

## 12. Następny krok walidacyjny

Na tym samym historycznym oknie:

```text
2026-08-10T12:00:00Z..12:15:00Z
179 próbek
```

należy uruchomić `ventilation-v5-simple` i ocenić przede wszystkim jakość wniosków:

- czy Qwen widzi spadek PM na obu węzłach,
- czy widzi wzrost VOC na obu węzłach,
- czy poprawnie opisuje temperaturę/wilgotność i kondycję SENSOR BUS,
- czy nie traktuje STOP jako usterki bez podstawy,
- czy jawnie uwzględnia brak historycznego baseline'u.

Dopiero po jakościowym PASS można przejść do testu i uruchomienia timera systemd.
