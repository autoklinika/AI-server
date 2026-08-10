# ADR-005 – Wykonywanie analiz wentylacji przez Qwen

**Status:** Zatwierdzone do walidacji Stage 2  
**Data:** 10.08.2026

## Kontekst

Stage 1 zapewnia działający i zwalidowany tor:

```text
CM5 -> AI Bridge -> PostgreSQL
```

Dane RAW są zapisywane niezależnie od Ollamy i Qwena. Kolejnym krokiem jest uruchomienie rzeczywistej interpretacji danych przez lokalny model `qwen3.6:35b`.

Nadal obowiązuje nadrzędna zasada:

> CM5 steruje systemem. Python przygotowuje dane. Qwen interpretuje dane. AI doradza, ale nigdy nie steruje wentylacją.

## Decyzja 1 – analiza poza ścieżką ingestu

Qwen nie jest wywoływany przez endpoint telemetryczny. Ingest kończy się po walidacji, transakcyjnym zapisie do PostgreSQL i ACK dla CM5.

Analiza jest osobnym procesem:

```text
PostgreSQL RAW
   ↓
matematyczna agregacja Python
   ↓
prompt domenowy ventilation
   ↓
Ollama /api/chat
   ↓
qwen3.6:35b
   ↓
walidacja struktury Pydantic
   ↓
ventilation_analysis_runs
```

Wolna odpowiedź modelu, awaria Ollamy albo błąd odpowiedzi AI nie wpływa na przyjmowanie telemetrii ani na CM5.

## Decyzja 2 – zamknięte, wyrównane okna 15-minutowe

Analiza wykorzystuje zamknięte okna kalendarzowe:

```text
12:00:00 <= captured_at < 12:15:00
12:15:00 <= captured_at < 12:30:00
12:30:00 <= captured_at < 12:45:00
...
```

Nie używamy przesuwającego się zakresu „ostatnie 15 minut”, ponieważ utrudniałby idempotencję i porównywanie wyników historycznych.

Docelowy timer jest planowany na `:00:30`, `:15:30`, `:30:30`, `:45:30`.

## Decyzja 3 – Python wykonuje przygotowanie matematyczne

Python nie definiuje progów anomalii jakości powietrza i nie podejmuje decyzji, że wystąpiła anomalia.

Dla danych liczbowych oblicza m.in.:

- count,
- missing,
- mean,
- min,
- max,
- standard deviation,
- first,
- last,
- delta,
- liniowy slope na minutę,
- udział wartości logicznych true,
- zmiany liczników diagnostycznych.

Qwen otrzymuje te statystyki i dokonuje interpretacji.

## Decyzja 4 – minimalna jakość danych przed wywołaniem modelu

Przy capture CM5 co 5 s pełne okno 15-minutowe powinno zawierać około 180 próbek.

Stage 2 przyjmuje domyślne minimum:

```text
120 próbek
```

Jest to deterministic data-quality gate, a nie próg anomalii. Przy mniejszej liczbie próbek Qwen nie jest uruchamiany i zapisujemy `insufficient_data`.

## Decyzja 5 – prosty structured output

Ollama jest wywoływana przez:

```text
POST http://127.0.0.1:11434/api/chat
```

Dla aktywnego profilu walidacyjnego:

```text
stream=false
think=true
temperature=0
format=<JSON Schema VentilationAnalysisResult>
```

Aktywny kontrakt `VentilationAnalysisResult` jest celowo płaski:

```text
schema_version
status
summary
confidence
observations[]        # lista tekstów
anomalies[]           # lista tekstów
recommendations[]     # lista tekstów
data_quality_notes[]  # lista tekstów
```

Pydantic sprawdza strukturę, dozwolony status, typy pól oraz podstawowe zakresy, np. `confidence` 0..1.

## Decyzja 6 – walidacja nie może zastępować interpretacji AI

Walidacja runtime nie ocenia semantycznie jakości rozumowania modelu.

Nie wymuszamy przez Python:

- minimalnej liczby obserwacji,
- obowiązkowego cytowania konkretnych ścieżek z `input_summary`,
- `provenance` ani `provenance_paths`,
- reguł typu „Qwen musi wspomnieć pole X”,
- progów uznających trend lub wartość za anomalię.

Powód: podczas walidacji `ventilation-v1..v4` zbyt rozbudowany kontrakt zaczął sprawdzać zdolność modelu do wypełniania formularza zamiast jakość jego interpretacji danych.

Python ma przygotować wiarygodną matematykę i bezpiecznie obsłużyć wynik. Qwen ma interpretować.

## Decyzja 7 – prompt ma być krótki i domenowy

Aktualny profil:

```text
ventilation-v6-thinking
```

`ventilation-v6-thinking` zachowuje ten sam krótki prompt i ten sam płaski schema co `ventilation-v5-simple`. Kontrolowany eksperyment A/B zmienia wyłącznie tryb modelu:

```text
v5-simple   -> think=false
v6-thinking -> think=true
```

Prompt przypomina modelowi najważniejsze fakty domenowe:

- analizować stan sterownika i SENSOR BUS,
- porównywać oba SEN55,
- analizować PM, VOC, NOx, temperaturę i wilgotność oraz trendy,
- opierać wnioski wyłącznie na przekazanych danych,
- podawać istotne liczby w uzasadnieniu, gdy są pomocne,
- nie wymyślać historycznego baseline'u,
- nie traktować STOP + setpoint 0 V jako usterki, ponieważ oczekiwany stan pracy nie jest znany,
- pamiętać, że setpointy 0–10 V są wartościami zadanymi, a nie pomiarem RPM/przepływu,
- nie sterować systemem.

## Decyzja 8 – reasoning jest częścią wersjonowanego profilu

Dla aktywnego `ventilation-v6-thinking` ustawiamy:

```text
think=true
```

Tryb thinking jest związany z wersją profilu analizy, a nie z przypadkową zmienną środowiskową. Dzięki temu idempotentny klucz `(source_id, window_start, window_end, model, prompt_version)` oznacza również jednoznaczny tryb inferencji.

Ollama może zwracać wewnętrzne pole `message.thinking`, ale AI Bridge go nie zapisuje. Przechowywany jest wyłącznie końcowy structured output oraz metryki wykonania.

## Decyzja 9 – idempotencja analiz

Jednoznaczność analizy jest określona przez:

```text
source_id
+ window_start
+ window_end
+ model
+ prompt_version
```

Ponowne uruchomienie tego samego okna zwraca istniejący wynik i nie wywołuje Qwena ponownie.

Zmiana `prompt_version` lub modelu pozwala świadomie wykonać nową interpretację tego samego materiału historycznego.

## Decyzja 10 – osobna tabela wyników

Wyniki są przechowywane w `ventilation_analysis_runs`. Nie modyfikujemy danych RAW.

Tabela zawiera m.in.:

- `analysis_id`,
- `source_id`,
- `window_start`,
- `window_end`,
- `created_at`,
- `model`,
- `prompt_version`,
- `sample_count`,
- `status`,
- `input_summary`,
- `result`,
- `raw_response`,
- `prompt_eval_count`,
- `eval_count`,
- `total_duration_ns`.

## Ograniczenia Stage 2

Na tym etapie:

- nie ma automatycznego sterowania,
- nie ma endpointu sterującego,
- nie ma uczenia/fine-tuningu modelu,
- nie ma jeszcze historycznego baseline'u 12-miesięcznego,
- timer jest przygotowany, ale nie powinien być włączany przed ręczną walidacją `ventilation-v6-thinking` na rzeczywistych danych,
- jeden trigger timera analizuje ostatnie zakończone okno; pełny automatyczny backfill wielu pominiętych okien po długiej awarii może zostać dodany później.

## Wniosek

Stage 2 ma pozostać prosty: Python przygotowuje deterministyczne statystyki, Qwen je interpretuje, a Pydantic pilnuje wyłącznie bezpiecznego kontraktu danych. Aktualny test sprawdza, czy włączenie reasoning poprawia jakość interpretacji bez dokładania kolejnych walidatorów i bez zmiany danych, promptu ani schema.
