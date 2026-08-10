# ADR-005 – Wykonywanie analiz wentylacji przez Qwen

**Status:** Zatwierdzone do walidacji Stage 2  
**Data:** 10.08.2026

## Kontekst

Stage 1 zapewnia działający i zwalidowany tor:

```text
CM5 -> AI Bridge -> PostgreSQL
```

Dane RAW są zapisywane niezależnie od Ollamy i Qwena. Nadal obowiązuje nadrzędna zasada:

> CM5 steruje systemem. Python przygotowuje dane. Qwen interpretuje dane. AI doradza, ale nigdy nie steruje wentylacją.

## Decyzja 1 – analiza poza ścieżką ingestu

Qwen nie jest wywoływany przez endpoint telemetryczny. Ingest kończy się po walidacji, transakcyjnym zapisie do PostgreSQL i ACK dla CM5.

Aktywny tor analizy:

```text
PostgreSQL RAW
   ↓
pełna matematyczna agregacja Python
   ↓
pełny input_summary (audit/storage)
   ↓
kompaktowy analysis packet dla Qwena
   ↓
krótki prompt domenowy/reportingowy
   ↓
Ollama /api/chat
   ↓
qwen3.6:35b, think=true
   ↓
prosta walidacja struktury Pydantic
   ↓
ventilation_analysis_runs
```

Awaria modelu lub procesu analizy nie wpływa na CM5 ani na przyjmowanie telemetrii.

## Decyzja 2 – zamknięte, wyrównane okna 15-minutowe

Analiza wykorzystuje zamknięte okna:

```text
12:00:00 <= captured_at < 12:15:00
12:15:00 <= captured_at < 12:30:00
12:30:00 <= captured_at < 12:45:00
...
```

Docelowy timer jest planowany 30 s po każdym kwartale.

## Decyzja 3 – Python wykonuje przygotowanie matematyczne

Python nie definiuje progów anomalii i nie klasyfikuje jakości powietrza.

Pełny `input_summary` może zawierać m.in.:

- count,
- missing,
- mean,
- min,
- max,
- stddev,
- first,
- last,
- delta,
- slope_per_minute,
- udziały wartości logicznych,
- zmiany liczników diagnostycznych.

Qwen odpowiada za interpretację.

## Decyzja 4 – minimalna jakość danych przed Qwenem

Przy capture co około 5 s pełne okno 15-minutowe powinno mieć około 180 próbek.

Domyślny gate Stage 2:

```text
120 próbek
```

Przy mniejszej liczbie próbek Qwen nie jest wywoływany i zapisywany jest `insufficient_data`.

## Decyzja 5 – prosty structured output

Ollama jest wywoływana przez:

```text
POST http://127.0.0.1:11434/api/chat
```

Aktywny profil:

```text
model=qwen3.6:35b
stream=false
think=true
temperature=0
format=<JSON Schema VentilationAnalysisResult>
```

Kontrakt wyniku pozostaje płaski:

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

Pydantic sprawdza strukturę, typy, dozwolony status i podstawowe zakresy. Nie ocenia semantycznie jakości rozumowania modelu.

## Decyzja 6 – walidacja nie zastępuje interpretacji AI

Po eksperymentach `ventilation-v3/v4` rezygnujemy z runtime provenance, obowiązkowego pokrycia pól i sztucznej minimalnej liczby obserwacji.

Python nie wymusza:

- `provenance` ani `provenance_paths`,
- cytowania konkretnych ścieżek,
- minimalnej liczby observations,
- reguły „Qwen musi wspomnieć pole X”,
- progów anomalii.

Powód: taka walidacja zaczęła mierzyć zdolność modelu do wypełniania formularza, a nie jakość jego interpretacji.

## Decyzja 7 – compact analysis packet

`ventilation-v7-compact-thinking` potwierdził, że kierunek kompaktowego wejścia jest właściwy. Na tym samym oknie 179 próbek Qwen poprawnie zauważył:

- rosnący VOC,
- lekko spadające PM,
- stabilną temperaturę i wilgotność,
- płaski NOx,
- brak historycznego baseline'u.

Model przestał twierdzić, że wilgotność jest niedostępna. Jednocześnie odpowiedź była nadal słaba raportowo: po angielsku, z pustym `observations`, niepotrzebnym tekstem typu `Ready to convert, plot...` oraz z bardzo wysokim `confidence=0.98`.

Wniosek: packet pozostaje bez zmian. Problem v7 dotyczy formy raportowania, nie selekcji danych.

Packet zachowuje:

- okno i sample_count,
- `historical_baseline_available`,
- `expected_operating_state_known`,
- tryb, setpointy, readiness i alarmy,
- kondycję SENSOR BUS,
- oba węzły SEN55,
- dla każdego odczytu: `count`, `missing`, `mean`, `min`, `max`, `delta`, `slope_per_minute`,
- delty liczników diagnostycznych,
- informację, które pomiary są obecne,
- jawne `not_provided_by_system = [co2, fan_rpm, airflow]`.

Packet usuwa z materiału przekazywanego modelowi pola mniej potrzebne do bieżącej interpretacji, m.in. `stddev`, `first`, `last`, szczegóły firmware/map/sequence i pełne rekordy liczników.

To jest wyłącznie kompresja danych. Python nadal nie interpretuje trendów i nie stosuje progów.

## Decyzja 8 – profil raportowania v8

Aktywna wersja:

```text
ventilation-v8-reporting
```

`v8` zachowuje bez zmian:

- compact analysis packet z v7,
- model `qwen3.6:35b`,
- `think=true`,
- `temperature=0`,
- prosty structured JSON,
- brak semantycznych validatorów.

Zmienia się wyłącznie instrukcja raportowania w promptcie. Model ma:

- odpowiadać wyłącznie po polsku,
- wykorzystywać `observations` do opisania najważniejszych faktów i trendów,
- nie dodawać meta-ofert typu `ready to plot`,
- nie nazywać jakości danych absolutnie `idealną/perfect`,
- utrzymywać logiczną zgodność `status=anomaly` z niepustym `anomalies`,
- uwzględniać brak baseline'u przy deklarowaniu confidence,
- nie rekomendować diagnostyki STOP wyłącznie dlatego, że tryb to STOP.

Te zasady są częścią promptu, a nie walidacji Python. Qwen nadal odpowiada za semantyczną interpretację.

## Decyzja 9 – pełny input_summary pozostaje źródłem audytowym

Do PostgreSQL nadal zapisujemy pełny `input_summary` obliczony z RAW.

Compact analysis packet jest deterministycznie generowany na potrzeby inferencji. Nie zastępuje pełnego materiału audytowego.

Dzięki temu można później odtworzyć, zweryfikować lub ponownie przeanalizować historyczne okno bez utraty informacji.

## Decyzja 10 – reasoning jest częścią wersjonowanego profilu

Dla `ventilation-v8-reporting`:

```text
think=true
```

Tryb thinking jest związany z profilem, nie z przypadkową zmienną `.env`. Idempotentny klucz `(source_id, window_start, window_end, model, prompt_version)` jednoznacznie określa również tryb inferencji i format materiału wejściowego.

Pole `message.thinking` nie jest zapisywane. Przechowywany jest tylko końcowy structured output i metryki wykonania.

## Decyzja 11 – idempotencja i historia wyników

Unikalność analizy:

```text
source_id
+ window_start
+ window_end
+ model
+ prompt_version
```

Zmiana wersji profilu pozwala wykonać nową interpretację tego samego okna bez kasowania wyników wcześniejszych eksperymentów.

## Ograniczenia Stage 2

Na tym etapie:

- nie ma automatycznego sterowania,
- nie ma endpointu sterującego,
- nie ma fine-tuningu,
- nie ma jeszcze wiarygodnego historycznego baseline'u warsztatu,
- timer pozostaje niewłączony do jakościowego PASS `ventilation-v8-reporting`,
- automatyczny backfill wielu pominiętych okien nie jest jeszcze zaimplementowany.

## Wniosek

Stage 2 pozostaje prosty architektonicznie: Python oblicza i porządkuje dane, Qwen interpretuje, Pydantic pilnuje kontraktu. `ventilation-v8-reporting` zachowuje udany compact packet z v7 i testuje już tylko jakość końcowego raportu modelu.
