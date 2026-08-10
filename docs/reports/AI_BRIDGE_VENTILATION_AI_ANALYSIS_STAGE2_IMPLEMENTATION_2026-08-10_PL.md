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

Python oblicza pełne statystyki matematyczne, stan sterownika, setpointy, alarmy, SENSOR BUS, oba SEN55 i liczniki diagnostyczne. Pełny `input_summary` pozostaje w PostgreSQL jako audit/history.

Do Qwena trafia compact packet zawierający tylko dane potrzebne do bieżącej interpretacji. Python nie definiuje progów i nie klasyfikuje jakości powietrza.

## 5. Ewolucja profilu

Najważniejsze wnioski z v1-v9:

- `think=true` poprawił zauważanie trendów,
- compact packet poprawił poprawność odczytu PM/VOC/humidity/temperature/NOx,
- provenance i semantyczne walidatory były zbyt rozbudowane,
- wielopolowy output zachęcał model do pustych list,
- minimalny schema v2 rozwiązał problem formatu i języka,
- potrzebna była jawna ochrona przed wymyślaniem norm/progów bez baseline'u.

## 6. Końcowy profil – `ventilation-v10-baseline-safe`

Kontrakt:

```text
schema_version = 2
status
analysis_pl
operator_recommendation_pl
data_quality_pl
```

Statusy:

```text
no_anomaly_detected
attention
anomaly
insufficient_data
```

Wszystkie trzy pola tekstowe są obowiązkowe i mają być po polsku.

`no_anomaly_detected` oznacza wyłącznie brak jednoznacznej anomalii w danym oknie, nie historyczną normalność, bezpieczeństwo ani zgodność z normą.

## 7. Walidacja funkcjonalna i idempotencja

Historyczne okno 179 próbek:

```text
analysis_id=2dbf4563-e18b-47db-a3d8-18cb6f8f79e7
prompt_version=ventilation-v10-baseline-safe
schema_version=2
status=no_anomaly_detected
reused_existing=false
```

Drugi przebieg zwrócił ten sam `analysis_id`, `reused_existing=true` i nie uruchomił nowego `POST /api/chat`.

**Idempotencja: PASS.**

## 8. Deployment produkcyjny

Stage 2 został wdrożony do `/opt/ai-bridge`.

Produkcja:

```text
ai-bridge 0.2.0
setuptools 84.0.0
ai-bridge.service = active (running)
```

`/health` po aktualizacji:

```text
status=ok
service=ai-bridge
version=0.2.0
control_commands_supported=false
database=ok
ollama=not_checked
```

## 9. Produkcyjny systemd oneshot – PASS

`ai-bridge-analysis.service` wykonał rzeczywistą analizę produkcyjną.

Systemd:

```text
ActiveState=inactive
SubState=dead
Result=success
ExecMainStatus=0
```

Rzeczywisty przebieg:

```text
analysis_id=5cf9d21e-e2d2-4b0c-920e-c4a67aef135a
window=2026-08-10T15:15:00Z..15:30:00Z
sample_count=180
prompt_version=ventilation-v10-baseline-safe
status=no_anomaly_detected
HTTP 200 OK
wall_clock≈90s
```

Wynik został zapisany do PostgreSQL.

**Produkcja `/opt/ai-bridge` + systemd oneshot: PASS.**

## 10. Znane ograniczenia jakości Qwena

Pipeline techniczny jest stabilny, ale treść modelu nadal może być semantycznie zbyt swobodna. Produkcyjny przebieg pokazał m.in.:

- arbitralny próg `PM >25 µg/m³`,
- arbitralny próg wilgotności `<40%`,
- meta-ofertę dotyczącą WHO/UE, wykresów i dalszej integracji,
- sugestię zmiany częstotliwości próbkowania lub alertów,
- zbyt mocne wnioski o jakości powietrza bez baseline'u.

To ograniczenie jest jawnie zaakceptowane. Nie tworzymy v11/v12 w Stage 2.

`ventilation-v10-baseline-safe` jest eksperymentalno-doradczym fundamentem, nie zweryfikowaną diagnozą ani instrukcją operatorską.

Pole `operator_recommendation_pl` nie może być wejściem do automatycznej logiki CM5.

## 11. Timer

Timer jest przygotowany, ale **pozostaje celowo niewłączony**.

Produkcja i oneshot są technicznie gotowe. Wstrzymanie automatyzacji wynika z jakości semantycznej raportu i decyzji, że przed cyklicznym udostępnianiem operatorowi należy najpierw zbudować read-only kanał z jawnym oznaczeniem `advisory/experimental`.

## 12. Następny etap – read-only wynik dla CM5

Planowany tor:

```text
ventilation_analysis_runs
    ↓
AI Bridge read-only endpoint – latest analysis
    ↓
CM5 advisory client
    ↓
cache/status/GUI operatora
```

Zasady:

- CM5 nie czeka na AI w logice sterowania,
- brak AI nie wpływa na wentylację,
- raport może być wyświetlany lub logowany,
- raport musi być oznaczony jako advisory/experimental,
- raport AI nie może automatycznie zmieniać trybu ani setpointów,
- nie będzie endpointu pozwalającego AI sterować CM5.

## 13. Status

Stage 2 ma funkcjonalny PASS, idempotencję PASS oraz produkcyjny systemd oneshot PASS. Interpretacja Qwena jest zamrożona na `ventilation-v10-baseline-safe`. Timer pozostaje wyłączony, a kolejnym etapem jest read-only kanał AI Server -> CM5. PR #3 pozostaje Draft do wyraźnej decyzji użytkownika o Ready/merge.