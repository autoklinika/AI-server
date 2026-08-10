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

Qwen nie jest wywoływany przez endpoint:

```text
POST /api/v1/ventilation/telemetry/batches
```

Ingest kończy się po walidacji, transakcyjnym zapisie do PostgreSQL i ACK dla CM5.

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
walidacja Pydantic
   ↓
ventilation_analysis_runs
```

Dzięki temu wolna odpowiedź modelu, awaria Ollamy albo błąd odpowiedzi AI nie wpływa na przyjmowanie telemetrii ani na CM5.

## Decyzja 2 – zamknięte, wyrównane okna 15-minutowe

Analiza wykorzystuje zamknięte okna kalendarzowe:

```text
12:00:00 <= captured_at < 12:15:00
12:15:00 <= captured_at < 12:30:00
12:30:00 <= captured_at < 12:45:00
...
```

Nie używamy przesuwającego się zakresu typu „ostatnie 15 minut”, ponieważ utrudniałby idempotencję i porównywanie wyników historycznych.

Docelowy timer jest planowany na:

```text
:00:30
:15:30
:30:30
:45:30
```

30 sekund opóźnienia daje czas na zapis ostatnich próbek okna do PostgreSQL.

## Decyzja 3 – Python wykonuje wyłącznie przygotowanie matematyczne

Python nie definiuje progów anomalii jakości powietrza i nie podejmuje decyzji, że wystąpiła anomalia.

Dla każdego parametru może obliczać m.in.:

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

Jest to deterministic data-quality gate, a nie próg anomalii.

Przy mniejszej liczbie próbek Qwen nie jest uruchamiany. Zapisujemy wynik `insufficient_data`.

## Decyzja 5 – structured outputs

Ollama jest wywoływana przez:

```text
POST http://127.0.0.1:11434/api/chat
```

z:

```json
{
  "stream": false,
  "format": "<JSON Schema VentilationAnalysisResult>",
  "think": false,
  "options": {
    "temperature": 0
  }
}
```

Odpowiedź jest następnie ponownie walidowana przez Pydantic.

Jeżeli odpowiedź nie spełnia schematu, analiza kończy się błędem i nie jest traktowana jako poprawny wynik.

## Decyzja 6 – brak przechowywania toku rozumowania

Dla `qwen3.6:35b` ustawiamy:

```text
think=false
```

Nie potrzebujemy przechowywać pola thinking ani wewnętrznego toku rozumowania modelu. Przechowywany jest wyłącznie końcowy, strukturalny wynik doradczy oraz metryki wykonania.

## Decyzja 7 – idempotencja analiz

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

## Decyzja 8 – osobna tabela wyników

Wyniki są przechowywane w:

```text
ventilation_analysis_runs
```

Nie modyfikujemy danych RAW.

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

## Format wyniku Qwena

Qwen zwraca strukturalnie:

- status: `normal`, `attention`, `anomaly` albo `insufficient_data`,
- summary,
- confidence,
- observations,
- anomalies,
- recommendations,
- data_quality_notes.

Rekomendacje są wyłącznie dla operatora. Nie są komendami dla CM5.

## Ograniczenia Stage 2

Na tym etapie:

- nie ma automatycznego sterowania,
- nie ma endpointu sterującego,
- nie ma uczenia/fine-tuningu modelu,
- nie ma jeszcze historycznego baseline'u 12-miesięcznego,
- timer jest przygotowany, ale nie powinien być włączany przed ręczną walidacją na rzeczywistych danych,
- jeden trigger timera analizuje ostatnie zakończone okno; pełny automatyczny backfill wielu pominiętych okien po długiej awarii może zostać dodany w kolejnym etapie.

## Wniosek

Stage 2 dodaje rzeczywistą warstwę interpretacji AI, zachowując całkowitą separację od sterowania i od krytycznej ścieżki ingestu.
