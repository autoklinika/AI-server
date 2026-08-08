# AI Bridge Stage 1 — clean foundation

**Data:** 08.08.2026  
**Status:** implementacja na gałęzi roboczej do walidacji na Serwerze AI  
**Zakres:** wyłącznie fundament AI Bridge i przyjmowanie telemetrii `ventilation`

## Punkt startowy

Implementacja została napisana od zera z aktualnego `main` @ `e159e187fea0403ba1adc2b889c20eb766994353`, po zatwierdzeniu:

- `docs/VENTILATION_TELEMETRY_API_V1_PL.md`,
- `docs/VENTILATION_TELEMETRY_DATA_MODEL_V1_PL.md`.

Nie bazuje na wcześniejszym kodzie Draft PR #1.

## Zaimplementowano

- układ `src/ai_bridge`,
- FastAPI,
- Pydantic Settings,
- ścisłe modele Pydantic odpowiadające rzeczywistemu `CoreState` CM5,
- endpoint `POST /api/v1/ventilation/telemetry/batches`,
- ACK po transakcyjnym zapisie,
- idempotencję `source_id + batch_id`,
- idempotencję `source_id + sample_id`,
- wykrywanie duplikatu `sample_id` wewnątrz jednego batcha,
- konflikt HTTP 409 przy ponownym użyciu `batch_id` z innym payloadem,
- SQLAlchemy 2,
- migrację Alembic,
- warstwę storage możliwą do uruchomienia na PostgreSQL,
- SQLite jako lokalny backend deweloperski/testowy,
- `/health`,
- limit `Content-Length` dla telemetrii 1 MiB,
- jawny brak endpointów sterujących,
- cienką, niewykorzystywaną jeszcze granicę Ollama,
- testy API, walidacji i idempotencji.

## Walidacja przed publikacją

Wykonano lokalnie:

```text
python -m compileall: PASS
pytest:                 11/11 PASS
Alembic upgrade head:   PASS
```

Migracja utworzyła oczekiwane struktury:

```text
alembic_version
ventilation_ingest_batches
ventilation_telemetry_raw
```

Testy obejmują między innymi:

- standardowy zapis batcha,
- retransmisję tej samej paczki bez duplikacji,
- częściowo nakładające się batche,
- konflikt ponownie użytego `batch_id` z inną treścią,
- nieobsługiwaną wersję schematu,
- brak strefy czasowej w timestampie,
- nieznane pole telemetryczne, np. niezaimplementowane RPM,
- brak endpointów sterujących w OpenAPI,
- duplikat `sample_id` wewnątrz batcha,
- prawidłowy `sensor_bus=null` zgodny z kształtem `CoreState`,
- odrzucenie requestu przekraczającego 1 MiB według `Content-Length`.

## Świadomie poza Stage 1

- Qwen i wykonywanie analiz,
- agregacja 15-minutowa,
- baseline,
- Knowledge Base / RAG,
- historia dla GUI CM5,
- tacho/RPM,
- AERO BUS,
- adapter CRT,
- uwierzytelnianie API,
- połączenie z rzeczywistym CM5.

## Baza danych

Kod używa SQLAlchemy i `AI_BRIDGE_DATABASE_URL`.

Dla development/test domyślny URL to SQLite. Na docelowym Serwerze AI planowany jest PostgreSQL, np.:

```text
postgresql+psycopg://ai_bridge:HASLO@127.0.0.1/ai_bridge
```

Hasła nie mogą być commitowane do repozytorium.

Migracje:

```bash
alembic upgrade head
```

## Uruchomienie developerskie

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev,postgres]'
alembic upgrade head
ai-bridge
```

## Granica bezpieczeństwa

Endpoint telemetrii nie komunikuje się z Ollamą. Niedostępność Ollamy nie wpływa na zapis telemetrii ani ACK.

AI Bridge nie udostępnia endpointów sterujących. CM5 pozostaje jedynym autonomicznym sterownikiem wentylacji.
