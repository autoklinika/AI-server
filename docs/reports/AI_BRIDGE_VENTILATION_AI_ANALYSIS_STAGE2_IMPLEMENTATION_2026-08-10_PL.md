# AI Bridge – Ventilation AI Analysis Stage 2

**Data:** 10.08.2026  
**Status:** BASE FOUNDATION PASS – `ventilation-v10-baseline-safe`; idempotency/deployment pending  
**Repozytorium:** `autoklinika/AI-server`  
**Gałąź:** `agent/ventilation-ai-analysis-stage2`

## 1. Cel

Dodać prostą i bezpieczną warstwę interpretacji danych wentylacji przez lokalny model `qwen3.6:35b`, pozostawiając pełne sterowanie i safety po stronie CM5.

```text
PostgreSQL RAW
    ↓
Python – pełne statystyki matematyczne
    ↓
pełny input_summary – audit/history
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

AI nie znajduje się na ścieżce sterowania ani ACK CM5.

## 2. Granica bezpieczeństwa

```text
CM5 = sterowanie + safety
Python = matematyka + infrastruktura
Qwen = interpretacja + rekomendacje
```

Awaria AI Servera lub Qwena nie wpływa na wentylację.

## 3. Okna i data-quality gate

Analiza działa na zamkniętych oknach 15-minutowych. Przy capture co około 5 s pełne okno ma około 180 próbek.

Minimalny gate:

```text
120 próbek
```

Poniżej tego progu Qwen nie jest wywoływany; zapisywany jest wynik `insufficient_data`.

## 4. Przygotowanie danych

Python oblicza pełne statystyki, m.in.:

- count / missing,
- mean / min / max / stddev,
- first / last / delta,
- slope_per_minute,
- tryb i setpointy,
- alarmy,
- stan SENSOR BUS,
- oba SEN55,
- liczniki diagnostyczne.

Pełny `input_summary` jest zachowywany w PostgreSQL.

Do Qwena trafia compact packet zawierający tylko dane potrzebne do bieżącej interpretacji. Python nie definiuje progów ani nie klasyfikuje jakości powietrza.

## 5. Historia eksperymentów v1-v9

Wersje były walidowane na tym samym oknie:

```text
2026-08-10T12:00:00Z..12:15:00Z
179 próbek
```

Najważniejsze wnioski:

- v1/v2 – model zbyt płytko odczytywał pełny materiał i pomijał część trendów,
- v3/v4 – provenance i rozbudowane walidatory okazały się zbyt skomplikowane,
- v5 – prosty output przy `think=false` nadal był za płytki,
- v6 – `think=true` poprawił analizę trendów,
- v7 – compact packet wyraźnie poprawił odczyt PM/VOC/humidity/temperature/NOx,
- v8 – rozbudowane instrukcje raportowe nadal były ignorowane przez model,
- v9 – minimalny schema v2 rozwiązał problem formatu odpowiedzi i języka, ale model nadal użył pojęć sugerujących nieistniejące normy/progi.

### Rzeczywisty wynik v9

```text
analysis_id=db1198e8-71d8-4d1e-8b7c-b4291f91319c
prompt_version=ventilation-v9-simple-report
sample_count=179
HTTP 200 OK
status=no_anomaly_detected
schema_version=2
```

Format v9 uznano za właściwy. Wynik był po polsku i zawierał wszystkie trzy obowiązkowe pola.

Do poprawy pozostały nieuprawnione sformułowania sugerujące istnienie norm/progów, mimo że historyczny baseline warsztatu nie został jeszcze zbudowany.

## 6. Końcowy profil Stage 2 – `ventilation-v10-baseline-safe`

Aktywny kontrakt:

```text
schema_version = 2
status
analysis_pl
operator_recommendation_pl
data_quality_pl
```

Status:

```text
no_anomaly_detected
attention
anomaly
insufficient_data
```

Wszystkie trzy pola tekstowe są obowiązkowe i mają być napisane po polsku.

Compact packet, `think=true`, `temperature=0`, model i schema pozostają bez zmian.

Profil dodatkowo zabrania klasyfikowania wartości jako `w normie`, `typowe`, `bezpieczne` lub `nie przekraczające progów`, jeżeli odpowiednie normy, progi lub baseline nie zostały przekazane w danych.

`no_anomaly_detected` oznacza wyłącznie brak jednoznacznej anomalii w danym 15-minutowym oknie.

## 7. Rzeczywisty wynik v10

Dla tego samego okna 179 próbek otrzymano:

```text
analysis_id=2dbf4563-e18b-47db-a3d8-18cb6f8f79e7
prompt_version=ventilation-v10-baseline-safe
sample_count=179
HTTP 200 OK
status=no_anomaly_detected
schema_version=2
reused_existing=false
```

### Co zadziałało

- odpowiedź poprawnie przeszła structured output schema v2,
- wszystkie trzy pola tekstowe były po polsku,
- nie pojawiły się stwierdzenia `w normie`, `typowe`, `bezpieczne` ani `nie przekracza progów`,
- Qwen podał konkretne wartości pomiarowe i trend VOC/PM,
- wynik został zapisany do PostgreSQL.

### Znane ograniczenia, które świadomie odkładamy

Wynik nadal nie jest wystarczająco precyzyjny, aby traktować go jako instrukcję operatorską lub diagnozę:

- model opisał głównie wartości jednego z dwóch SEN55 zamiast równorzędnie zestawić oba węzły,
- dodał meta-tekst o gotowości do dalszej integracji z BMS/EMS,
- zalecił okresową kalibrację czujników bez podstawy wynikającej z analizowanego okna,
- zasugerował możliwą `aktywność chemiczną/wentylacyjną` jako interpretację VOC bez wystarczającej podstawy.

Te ograniczenia nie są teraz naprawiane kolejnymi wersjami promptu. Profil v10 zostaje przyjęty jako **prosty eksperymentalno-doradczy fundament**, który będziemy rozwijać później po zebraniu historycznego baseline'u.

## 8. Decyzja o zamrożeniu

Nie tworzymy v11/v12 w bieżącym Stage 2.

Do interpretacji wrócimy po zebraniu rzeczywistej historii warsztatu. Wtedy możliwe będzie oparcie dalszych funkcji na danych:

- baseline historyczny,
- porównania między oknami i dniami,
- progi/reguły wynikające z rzeczywistych danych,
- bardziej zaawansowane raporty.

## 9. PostgreSQL i idempotencja

Tabela `ventilation_analysis_runs` obsługuje schema v2 bez migracji:

- `status` to pole tekstowe,
- `result` to JSON,
- `input_summary` to JSON.

Idempotencja:

```text
(source_id, window_start, window_end, model, prompt_version)
```

Do końcowego potwierdzenia pozostaje ponowne uruchomienie dokładnie tego samego okna dla `ventilation-v10-baseline-safe`.

Oczekiwane:

```text
analysis_id=2dbf4563-e18b-47db-a3d8-18cb6f8f79e7
reused_existing=true
```

oraz brak nowego `POST /api/chat` do Ollamy.

## 10. Następny etap – wynik AI dla CM5

Po domknięciu Stage 2 kolejnym etapem będzie read-only dostarczenie najnowszego raportu do CM5.

Planowany kierunek:

```text
ventilation_analysis_runs
    ↓
AI Bridge read-only endpoint – latest analysis
    ↓
CM5 advisory client
    ↓
cache/status/GUI operatora
```

Najważniejsze zasady:

- CM5 nigdy nie czeka na AI w logice sterowania,
- brak połączenia z AI Serverem nie wpływa na wentylację,
- pobrany raport może być wyświetlany lub logowany,
- raport będzie oznaczony jako advisory/experimental,
- raport nie jest wejściem do automatycznej logiki setpointów,
- nie tworzymy żadnego endpointu pozwalającego AI sterować CM5.

Szczegółowy endpoint i klient CM5 będą osobnym etapem.

## 11. Co pozostaje do domknięcia Stage 2

1. realny test idempotencji v10,
2. deployment aktualnego kodu do `/opt/ai-bridge`,
3. oneshot systemd PASS,
4. dopiero potem decyzja o włączeniu timera,
5. PR pozostaje Draft do wyraźnej decyzji użytkownika o Ready/merge.

## 12. Status

Interpretacja Qwena jest zamrożona na `ventilation-v10-baseline-safe` jako prosta baza do późniejszej rozbudowy. Stage 2 nie jest jeszcze scalony; trwa domknięcie techniczne.