# AI Bridge – Ventilation AI Analysis Stage 2

**Data:** 10.08.2026  
**Status:** IMPLEMENTED – `ventilation-v10-baseline-safe` oczekuje na końcową walidację  
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

Do poprawy pozostały wyłącznie nieuprawnione sformułowania:

- `typowe dla aktywności warsztatowej`,
- `nie przekracza progów alarmowych`,
- `pozostałe parametry pozostają w normie`.

Na tym etapie nie istnieje jeszcze wiarygodny baseline historyczny warsztatu ani zdefiniowane progi jakości powietrza, więc takich stwierdzeń nie wolno traktować jako faktów.

## 6. Końcowy profil Stage 2 – `ventilation-v10-baseline-safe`

Aktywny kontrakt pozostaje bez zmian względem v9:

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

Zmienia się tylko końcowa zasada promptu: bez przekazanego baseline'u, norm lub progów Qwen nie może używać określeń:

- `w normie`,
- `typowe`,
- `bezpieczne`,
- `nie przekracza progów`.

`no_anomaly_detected` oznacza wyłącznie brak jednoznacznej anomalii w tym konkretnym 15-minutowym oknie na podstawie dostępnych danych.

## 7. Decyzja o zamrożeniu rozwoju interpretacji

Po ręcznym PASS `ventilation-v10-baseline-safe` rozwój promptu i kontraktu odpowiedzi zostaje zamrożony na obecnym poziomie.

Nie planujemy kolejnych wersji v11/v12 w bieżącym Stage 2.

Do rozbudowy analizy wrócimy dopiero po zgromadzeniu realnej historii warsztatu, aby oprzeć dalsze funkcje na danych zamiast na arbitralnych założeniach. Wtedy będzie można dodać m.in.:

- historyczny baseline,
- porównania między oknami i dniami,
- progi/reguły wynikające z rzeczywistych danych,
- bardziej rozbudowane raporty.

## 8. PostgreSQL i idempotencja

Tabela `ventilation_analysis_runs` obsługuje schema v2 bez dodatkowej migracji:

- `status` to pole tekstowe,
- `result` to JSON,
- `input_summary` to JSON.

Idempotencja:

```text
(source_id, window_start, window_end, model, prompt_version)
```

Dzięki `prompt_version=ventilation-v10-baseline-safe` to samo okno może zostać przeanalizowane ponownie bez usuwania wcześniejszych wyników.

## 9. Następny etap – wynik AI dla CM5

Po zakończeniu Stage 2 kolejnym etapem będzie read-only dostarczenie najnowszego raportu do CM5.

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
- raport nie jest wejściem do automatycznej logiki setpointów,
- nie tworzymy żadnego endpointu pozwalającego AI sterować CM5.

Szczegółowy endpoint i klient CM5 będą osobnym etapem po zakończeniu Stage 2.

## 10. Co pozostaje do walidacji Stage 2

Na AI Serverze:

1. `compileall`,
2. pełny `pytest`,
3. realny przebieg tego samego okna 179 próbek,
4. potwierdzenie `prompt_version=ventilation-v10-baseline-safe`,
5. sprawdzenie, że raport nie używa nieistniejących norm, baseline'u ani progów,
6. drugi przebieg tego samego okna dla idempotencji,
7. dopiero potem test deploymentu/systemd timer.

Timer nadal pozostaje niewłączony.

## 11. Status

Stage 2 pozostaje Draft. Nie oznaczać PR jako Ready i nie wykonywać merge przed ręcznym PASS `ventilation-v10-baseline-safe` na rzeczywistym Serwerze AI.
