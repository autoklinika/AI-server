# AI Bridge – Ventilation AI Analysis Stage 2

**Data:** 10.08.2026  
**Status:** PRODUCTION ONESHOT PASS – `ventilation-v10-baseline-safe`; timer intentionally disabled  
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

Profil zabrania klasyfikowania wartości jako `w normie`, `typowe`, `bezpieczne` lub `nie przekraczające progów`, jeżeli odpowiednie normy, progi lub baseline nie zostały przekazane w danych.

`no_anomaly_detected` oznacza wyłącznie brak jednoznacznej anomalii w danym 15-minutowym oknie.

## 7. Walidacja funkcjonalna v10

Dla historycznego okna 179 próbek otrzymano:

```text
analysis_id=2dbf4563-e18b-47db-a3d8-18cb6f8f79e7
prompt_version=ventilation-v10-baseline-safe
status=no_anomaly_detected
schema_version=2
reused_existing=false
```

Drugi przebieg tego samego okna zwrócił:

```text
analysis_id=2dbf4563-e18b-47db-a3d8-18cb6f8f79e7
reused_existing=true
```

bez nowego `POST /api/chat` do Ollamy.

**Idempotencja v10: PASS.**

## 8. Deployment produkcyjny

Kod Stage 2 został wdrożony do:

```text
/opt/ai-bridge
```

Pakiet produkcyjny został zaktualizowany do:

```text
ai-bridge 0.2.0
```

W produkcyjnym virtualenv brakowało `setuptools`, co powodowało błąd `Cannot import 'setuptools.build_meta'` podczas instalacji editable. Doinstalowano:

```text
setuptools 84.0.0
```

Następnie instalacja `ai-bridge 0.2.0` zakończyła się powodzeniem.

Po restarcie:

```text
ai-bridge.service = active (running)
```

Health check:

```json
{
  "status": "ok",
  "service": "ai-bridge",
  "version": "0.2.0",
  "control_commands_supported": false,
  "components": {
    "database": "ok",
    "ollama": "not_checked"
  }
}
```

## 9. Produkcyjny test systemd oneshot – PASS

Uruchomiono:

```text
ai-bridge-analysis.service
```

Wynik systemd:

```text
ActiveState=inactive
SubState=dead
Result=success
ExecMainStatus=0
```

`inactive/dead` jest stanem prawidłowym dla `Type=oneshot` po zakończeniu zadania.

Rzeczywista analiza produkcyjna:

```text
analysis_id=5cf9d21e-e2d2-4b0c-920e-c4a67aef135a
window=2026-08-10T15:15:00Z..15:30:00Z
sample_count=180
prompt_version=ventilation-v10-baseline-safe
status=no_anomaly_detected
HTTP 200 OK
```

Czas ścienny oneshota wyniósł około 1 min 30 s. Proces zakończył się poprawnie i zapisał wynik do PostgreSQL.

**Produkcja `/opt/ai-bridge` + systemd oneshot: PASS.**

## 10. Znane ograniczenia jakości odpowiedzi Qwena

Produkcyjny przebieg potwierdził, że schema i pipeline są stabilne, ale końcowy tekst modelu nadal może zawierać nieuprawnione treści semantyczne.

W tym przebiegu Qwen m.in.:

- dodał meta-ofertę dalszej integracji/wykresów/WHO/UE,
- zaproponował arbitralne progi `PM >25 µg/m³` i wilgotność `<40%`, których nie było w danych,
- zasugerował zmianę częstotliwości próbkowania lub alertów,
- użył sformułowań sugerujących ocenę jakości powietrza bez zbudowanego baseline'u.

Wniosek pozostaje bez zmian: nie tworzymy v11/v12 w Stage 2. `ventilation-v10-baseline-safe` jest **eksperymentalno-doradczym fundamentem**, a nie zweryfikowaną diagnozą ani instrukcją operatorską.

Pole `operator_recommendation_pl` nie może być wejściem do automatycznej logiki CM5.

## 11. Decyzja o zamrożeniu

Do interpretacji wrócimy po zebraniu rzeczywistej historii warsztatu. Wtedy możliwe będzie oparcie dalszych funkcji na danych:

- baseline historyczny,
- porównania między oknami i dniami,
- progi/reguły wynikające z rzeczywistych danych,
- bardziej zaawansowane raporty.

## 12. Następny etap – wynik AI dla CM5

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
- raport może być wyświetlany lub logowany,
- raport musi być oznaczony jako advisory/experimental,
- raport nie jest wejściem do automatycznej logiki setpointów,
- nie tworzymy żadnego endpointu pozwalającego AI sterować CM5.

## 13. Timer

Jednostka timer została przygotowana, ale **pozostaje celowo niewłączona** do czasu decyzji o sposobie wykorzystania eksperymentalnego raportu i rozpoczęcia read-only kanału do CM5.

Nie jest to blokada techniczna: produkcyjny oneshot jest PASS. Jest to świadoma granica produktu i bezpieczeństwa informacji dla operatora.

## 14. Status

Stage 2 ma funkcjonalny PASS, idempotencję PASS oraz produkcyjny systemd oneshot PASS. Interpretacja Qwena jest zamrożona na `ventilation-v10-baseline-safe`. PR pozostaje Draft do wyraźnej decyzji użytkownika o Ready/merge.