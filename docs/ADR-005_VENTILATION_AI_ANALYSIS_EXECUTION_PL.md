# ADR-005 – Wykonywanie analiz wentylacji przez Qwen

**Status:** Stage 2 – profil bazowy zamrożony do końcowej walidacji  
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
minimalny raport JSON schema v2
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

## Aktywny profil – `ventilation-v10-baseline-safe`

Eksperymenty v1-v9 wykazały, że:

- `think=true` poprawia zauważanie trendów,
- compact packet poprawia poprawność odczytania danych,
- rozbudowany formularz odpowiedzi nie wnosi obecnie wartości,
- minimalny schema v2 jest właściwą bazą do dalszej rozbudowy,
- przy braku historycznego baseline'u Qwen nie może używać pojęć sugerujących istnienie znanych norm lub progów.

Aktywny kontrakt:

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

`no_anomaly_detected` oznacza wyłącznie brak jednoznacznej anomalii w danym 15-minutowym oknie na podstawie dostępnych danych. Nie oznacza, że wartości są normalne, typowe, bezpieczne lub mieszczą się w progach.

Wszystkie trzy pola tekstowe są obowiązkowe i mają być napisane po polsku.

## Ochrona przed nieistniejącym baseline'em i progami

Profil `ventilation-v10-baseline-safe` jawnie zabrania modelowi używania określeń:

- `w normie`,
- `typowe`,
- `bezpieczne`,
- `nie przekracza progów`,

jeżeli odpowiedni baseline, norma lub próg nie został przekazany w danych.

Brak historycznego baseline'u oznacza, że Qwen może opisywać wartości, kierunek zmian i zależności w oknie, ale nie może klasyfikować ich względem normalnej pracy warsztatu.

Ta zasada pozostaje częścią promptu. Python nie wykonuje semantycznej klasyfikacji odpowiedzi.

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

Pydantic sprawdza wyłącznie strukturę i typy.

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

Wynik jest przechowywany jako JSON w `ventilation_analysis_runs`, a `status` jako zwykłe pole tekstowe. Schema v2 nie wymaga dodatkowej migracji bazy.

Pełny `input_summary` nadal pozostaje zapisany jako materiał audytowy.

## Decyzja o zamrożeniu interpretacji Stage 2

Po końcowej walidacji `ventilation-v10-baseline-safe` nie rozwijamy dalej promptu ani kontraktu odpowiedzi w Stage 2.

Do rozbudowy interpretacji wrócimy dopiero po zebraniu rzeczywistej historii warsztatu, kiedy będzie można zaprojektować:

- historyczny baseline,
- porównania między oknami i dniami,
- progi lub reguły oparte na rzeczywistych danych,
- bardziej rozbudowane raporty i klasyfikacje.

## Następny etap – odczyt wyniku przez CM5

Po zakończeniu Stage 2 planowany jest **wyłącznie read-only kanał AI Server -> CM5**.

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
- brak odpowiedzi AI nie powoduje zmiany pracy wentylacji,
- wynik AI może być wyświetlany, logowany lub udostępniany operatorowi,
- wynik AI nie może automatycznie zmieniać trybu, setpointów ani żadnego elementu sterowania,
- nie będzie endpointu AI -> CM5 wykonującego komendy sterujące.

Szczegółowy kontrakt read-only endpointu i klienta CM5 zostanie zaprojektowany w kolejnym etapie.

## Ograniczenia bieżącego Stage 2

- brak automatycznego sterowania przez AI,
- brak endpointu sterującego,
- brak fine-tuningu,
- brak pełnego historycznego baseline'u warsztatu,
- timer analizy nadal niewłączony do końcowej walidacji `ventilation-v10-baseline-safe`,
- odczyt wyniku przez CM5 jeszcze niezaimplementowany.

## Wniosek

Stage 2 kończymy na prostej bazie: Python liczy i przygotowuje dane, Qwen tworzy krótki raport po polsku bez wymyślania nieistniejących norm i progów, a wynik trafia do PostgreSQL. Kolejny etap dotyczy już dostarczenia tego raportu do CM5 w kanale read-only.
