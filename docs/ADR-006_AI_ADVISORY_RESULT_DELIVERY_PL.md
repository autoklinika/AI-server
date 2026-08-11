# ADR-006 – Read-only dostarczanie wyniku AI do CM5

**Data:** 11.08.2026  
**Status:** Stage 3 – produkcyjny endpoint read-only PASS  
**Repozytorium:** `autoklinika/AI-server`  
**Gałąź:** `agent/ai-result-delivery-stage3`

## 1. Nadrzędna zasada

> CM5 steruje systemem. AI Server dostarcza wyłącznie informację doradczą.

Kanał AI Server -> CM5 nie może stać się kanałem sterującym. Awaria endpointu, bazy, sieci lub klienta advisory nie może wpływać na `ventilation-core`, safety ani setpointy.

## 2. Zakres Stage 3

Dodany został wyłącznie read-only endpoint:

```text
GET /api/v1/ventilation/analysis/latest?source_id=<source_id>
```

Endpoint:

- czyta istniejący rekord z `ventilation_analysis_runs`,
- wybiera najnowszy rekord dla `source_id` według `window_end`, a następnie `created_at`,
- nie uruchamia Ollamy/Qwena,
- nie wykonuje żadnej analizy,
- nie zapisuje danych,
- nie przyjmuje komend sterujących.

Brak wyniku dla źródła zwraca HTTP 404 `analysis_not_found`.

## 3. Delivery schema v1

Kontrakt transportowy jest oddzielony od schema wyniku Qwena.

```json
{
  "delivery_schema_version": 1,
  "analysis_id": "...",
  "source_id": "workshop-ventilation-cm5-01",
  "window_start": "...",
  "window_end": "...",
  "created_at": "...",
  "sample_count": 180,
  "model": "qwen3.6:35b",
  "prompt_version": "ventilation-v10-baseline-safe",
  "advisory_only": true,
  "experimental": true,
  "control_actions_supported": false,
  "result": {
    "schema_version": 2,
    "status": "no_anomaly_detected",
    "analysis_pl": "...",
    "operator_recommendation_pl": "...",
    "data_quality_pl": "..."
  }
}
```

Twarde flagi bezpieczeństwa są częścią schematu:

```text
advisory_only = true
experimental = true
control_actions_supported = false
```

## 4. Dane celowo niedostarczane

Endpoint nie ujawnia materiału wewnętrznego analizy:

- `input_summary`,
- `raw_response`,
- `prompt_eval_count`,
- `eval_count`,
- `total_duration_ns`.

CM5 otrzymuje tylko dane potrzebne do identyfikacji i prezentacji raportu.

## 5. Storage

Stage 3 nie wymaga migracji Alembic. Odczyt korzysta z istniejącej tabeli:

```text
ventilation_analysis_runs
```

Dodano metodę repozytorium `get_latest(source_id=...)`.

## 6. API i bezpieczeństwo

Nowa ścieżka obsługuje tylko `GET`.

Nie dodano:

- `POST` dla analizy,
- `PUT/PATCH/DELETE`,
- endpointów `control`, `command`, `actuator`, `set-speed`,
- żadnej ścieżki AI -> setpointy CM5.

Health nadal deklaruje:

```text
control_commands_supported=false
```

## 7. Wersja aplikacji

Stage 3 podniósł AI Bridge do:

```text
0.3.0
```

## 8. Testy kontraktu – PASS

Dodane testy sprawdzają:

- 404 przy braku wyniku,
- wybór najnowszego rekordu,
- delivery schema v1,
- wszystkie trzy flagi bezpieczeństwa,
- nested result schema v2,
- brak pól audit/raw/runtime w odpowiedzi,
- wyłącznie metodę GET,
- brak endpointów sterujących.

Rzeczywista lokalna walidacja na AI Serverze 11.08.2026:

```text
python -m compileall -q src tests
pytest
26 passed, 1 warning in 0.17s
```

**Implementacja i testy lokalne Stage 3: PASS.**

## 9. Walidacja produkcyjna – PASS

AI Bridge został wdrożony produkcyjnie jako `0.3.0`.

Health:

```text
status=ok
service=ai-bridge
version=0.3.0
control_commands_supported=false
database=ok
ollama=not_checked
```

Rzeczywisty odczyt:

```text
GET /api/v1/ventilation/analysis/latest?source_id=workshop-ventilation-cm5-01
```

zwrócił:

```text
delivery_schema_version=1
analysis_id=5cf9d21e-e2d2-4b0c-920e-c4a67aef135a
source_id=workshop-ventilation-cm5-01
window=2026-08-10T15:15:00Z..15:30:00Z
sample_count=180
model=qwen3.6:35b
prompt_version=ventilation-v10-baseline-safe
advisory_only=true
experimental=true
control_actions_supported=false
result.schema_version=2
status=no_anomaly_detected
```

Endpoint zwrócił istniejący zapisany rekord i nie uruchamia ścieżki analizy ani klienta Ollamy. Timer analizy pozostaje wyłączony, więc odczyt `GET latest` nie tworzy nowej analizy.

**Produkcja AI Server Stage 3: PASS.**

## 10. Następny element toru

Po stronie CM5 działać ma osobny klient:

```text
AI Bridge GET latest
    ↓
wvc-ai-advisory.service
    ↓
/var/lib/workshop-ventilation/ai-advisory.json
    ↓
przyszły GUI/status operatora
```

Klient CM5 nie komunikuje się z socketem `ventilation-core` i nie zapisuje do jego stanu.

## 11. Status

AI Server Stage 3 ma lokalny PASS i produkcyjny PASS dla read-only endpointu. Kolejnym krokiem jest wdrożenie i walidacja klienta `wvc-ai-advisory.service` na rzeczywistym CM5.

PR pozostaje Draft. Nie oznaczać Ready i nie merge'ować bez wyraźnej decyzji użytkownika.
