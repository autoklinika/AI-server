# ADR-005 – Wykonywanie analiz wentylacji przez Qwen

**Status:** Zatwierdzone do walidacji Stage 2  
**Data:** 10.08.2026

## Nadrzędna zasada

> CM5 steruje systemem. Python przygotowuje dane. Qwen interpretuje dane. AI doradza, ale nigdy nie steruje wentylacją.

Awaria AI Servera, Ollamy, Qwena lub kanału odbioru rekomendacji nie może wpływać na logikę sterowania ani bezpieczeństwo CM5.

## Aktywny tor

```text
CM5 telemetry
   ↓
AI Bridge ingest
   ↓
PostgreSQL RAW
   ↓
pełna matematyczna agregacja Python
   ↓
pełny input_summary (audit/history)
   ↓
compact analysis packet
   ↓
Ollama / qwen3.6:35b / think=true
   ↓
prosty raport JSON
   ↓
Pydantic – walidacja struktury
   ↓
ventilation_analysis_runs
```

Qwen nie jest wywoływany w ścieżce ingest/ACK.

## Okna i jakość danych

Analiza korzysta z zamkniętych, wyrównanych okien 15-minutowych. Przy capture co około 5 s pełne okno ma około 180 próbek.

Domyślny data-quality gate:

```text
120 próbek
```

Przy mniejszej liczbie próbek Qwen nie jest wywoływany i zapisywany jest `insufficient_data`.

## Python – tylko matematyka i przygotowanie danych

Pełny `input_summary` zachowuje m.in.:

- count / missing,
- mean / min / max / stddev,
- first / last / delta,
- slope_per_minute,
- stan sterownika i setpointy,
- alarmy,
- SENSOR BUS,
- oba węzły SEN55,
- liczniki diagnostyczne.

Python nie definiuje progów anomalii i nie klasyfikuje jakości powietrza.

Do Qwena trafia mniejszy `compact analysis packet`, który usuwa redundancję, ale nie interpretuje danych. Packet zachowuje PM, VOC, NOx, temperaturę, wilgotność, stan systemu, SENSOR BUS i diagnostykę. Jawnie rozróżnia pomiary dostępne od niedostępnych (`co2`, `fan_rpm`, `airflow`).

## Aktywny profil – `ventilation-v9-simple-report`

Eksperymenty v1-v8 pokazały:

- `think=true` poprawia zauważanie trendów,
- compact packet poprawia poprawność odczytania danych,
- rozbudowany formularz odpowiedzi (`observations`, `anomalies`, `recommendations`, `confidence`) nie wnosi obecnie wartości i zachęca model do pustych pól lub przypadkowego upychania całości w `summary`.

Dlatego aktywny kontrakt zostaje celowo uproszczony i przygotowany do późniejszej rozbudowy.

```text
schema_version = 2
status
analysis_pl
operator_recommendation_pl
data_quality_pl
```

Dozwolone statusy:

```text
no_anomaly_detected
attention
anomaly
insufficient_data
```

`no_anomaly_detected` oznacza wyłącznie brak podstaw do zgłoszenia anomalii w analizowanym oknie. Nie oznacza potwierdzenia historycznej „normalności” warsztatu.

Usunięto `confidence`, ponieważ przy braku historycznego baseline'u model zwracał wartości 0.98–1.0, które mogły być błędnie interpretowane jako wiarygodna pewność środowiskowa.

Wszystkie trzy pola tekstowe są obowiązkowe i mają być napisane po polsku.

## Structured output

Ollama:

```text
POST http://127.0.0.1:11434/api/chat
model=qwen3.6:35b
stream=false
think=true
temperature=0
format=<compact JSON Schema>
```

Pydantic sprawdza wyłącznie strukturę i typy. Python nie ocenia semantycznie odpowiedzi modelu.

## Idempotencja

Jednoznaczność analizy:

```text
source_id
+ window_start
+ window_end
+ model
+ prompt_version
```

Zmiana `prompt_version` pozwala ponownie przeanalizować to samo historyczne okno bez kasowania wcześniejszych wyników.

## PostgreSQL

Wynik jest przechowywany jako JSON w `ventilation_analysis_runs`, a `status` jako zwykłe pole tekstowe. Zmiana kontraktu na schema v2 nie wymaga migracji bazy.

Pełny `input_summary` nadal pozostaje zapisany jako materiał audytowy.

## Następny etap – odczyt wyniku przez CM5

Po ustabilizowaniu Stage 2 planowany jest **wyłącznie read-only kanał AI Server -> CM5**.

Docelowy kierunek:

```text
AI Server / ventilation_analysis_runs
        ↓
read-only HTTP endpoint latest analysis
        ↓
CM5 advisory client
        ↓
lokalny cache / GUI / status dla operatora
```

Zasady tego kanału:

- CM5 pobiera wynik asynchronicznie i nie czeka na niego w logice sterowania,
- brak odpowiedzi AI nie powoduje alarmu bezpieczeństwa ani zmiany pracy wentylacji,
- wynik AI może być wyświetlany, logowany lub udostępniany operatorowi,
- wynik AI nie może automatycznie zmieniać trybu, setpointów ani żadnego elementu sterowania,
- nie będzie endpointu AI -> CM5 wykonującego komendy sterujące.

Proponowany pierwszy endpoint będzie zwracał najnowszą zakończoną analizę dla `source_id`. Szczegółowy kontrakt zostanie zaprojektowany w kolejnym etapie.

## Ograniczenia bieżącego Stage 2

- brak automatycznego sterowania przez AI,
- brak endpointu sterującego,
- brak fine-tuningu,
- brak pełnego historycznego baseline'u warsztatu,
- timer analizy nadal niewłączony do końcowej walidacji `ventilation-v9-simple-report`,
- odczyt wyniku przez CM5 jeszcze niezaimplementowany.

## Wniosek

Bieżąca wersja ma być celowo prosta i stabilna: Python liczy i przygotowuje dane, Qwen tworzy jeden czytelny raport po polsku, a wynik jest zapisywany do PostgreSQL. Rozbudowa raportu i kanał read-only do CM5 będą kolejnymi etapami, bez naruszania granicy bezpieczeństwa.
