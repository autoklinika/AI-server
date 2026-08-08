# AI Bridge – Stage 1 Foundation

**Data:** 08.08.2026  
**Status:** implementacja startowa do walidacji na Serwerze AI

## Cel

Stage 1 tworzy pierwszy uruchamialny szkielet AI Bridge – wspólnej warstwy pośredniczącej między systemami źródłowymi, centralnym magazynem danych i lokalnym AI.

Pierwszym adapterem domenowym jest wentylacja (`ventilation_cm5`). Architektura pozostaje przygotowana na przyszły adapter CRT bez mieszania logiki obu projektów.

## Fundamentalna granica bezpieczeństwa

**AI Bridge ani Qwen nie sterują wentylacją.**

CM5 pozostaje odpowiedzialny za:

- odczyt czujników,
- sterowanie wentylatorami,
- logikę bezpieczeństwa,
- deterministyczne algorytmy sterowania,
- samodzielną pracę przy niedostępności Serwera AI.

AI Bridge może odbierać dane i zdarzenia oraz udostępniać wyniki analiz i rekomendacje. API celowo nie zawiera żadnego endpointu komend sterujących.

## Zakres Stage 1

Zaimplementowano:

- usługę HTTP/JSON opartą na FastAPI,
- wersjonowany kontrakt telemetrii,
- odbiór paczek telemetrycznych,
- ACK po poprawnym przyjęciu paczki,
- odporność na ponowne wysłanie tej samej paczki przez `batch_id`,
- pola `source`, `device_id`, `sequence` i znaczniki czasu ze strefą czasową,
- zapis pełnej paczki do SQLite,
- znormalizowany zapis pomiarów numerycznych do późniejszych zapytań historycznych,
- odbiór zdarzeń i odporność na duplikaty przez `event_id`,
- API historii przeznaczone m.in. dla GUI CM5,
- endpoint odczytu najnowszej rekomendacji,
- granicę modułu Ollama przygotowaną do późniejszej integracji,
- namespace adaptera wentylacji,
- endpoint stanu usługi,
- testy API.

Nie zaimplementowano jeszcze:

- wywoływania Qwena,
- agregacji 15-minutowej,
- budowania baseline'u,
- Knowledge Base / RAG,
- cyklicznych analiz,
- dodatkowej analizy AI po zdarzeniu krytycznym,
- backendu magazynu na NAS,
- uwierzytelniania i TLS,
- adaptera CRT.

## API v1

### Stan usługi

```text
GET /health
GET /api/v1/system/status
```

Odpowiedź jawnie zawiera:

```text
control_commands_supported: false
```

### Telemetria CM5 -> AI Bridge

```text
POST /api/v1/telemetry/batch
```

Przykład:

```json
{
  "schema_version": 1,
  "source": "ventilation_cm5",
  "device_id": "cm5-main",
  "batch_id": "20260808-000001-000123",
  "sequence": 123,
  "timestamp_start": "2026-08-08T00:00:00+02:00",
  "timestamp_end": "2026-08-08T00:00:05+02:00",
  "samples": [
    {
      "timestamp": "2026-08-08T00:00:00+02:00",
      "measurements": {
        "pm2_5": 11.2,
        "temperature": 23.4
      },
      "states": {
        "fan_1_percent": 35
      }
    }
  ]
}
```

Po poprawnym zapisie AI Bridge zwraca ACK. Ponowne wysłanie tej samej wartości `batch_id` jest bezpieczne – dane nie są zapisywane drugi raz, a odpowiedź zawiera `duplicate: true`.

### Zdarzenia

```text
POST /api/v1/events
```

CM5 może wysłać zdarzenie natychmiast, np. przy wykryciu krytycznego stanu. W późniejszym etapie takie zdarzenie może wyzwolić dodatkową analizę AI. Nie przekazuje to AI żadnych uprawnień sterujących.

### Historia

```text
GET /api/v1/history?metric=pm2_5&source=ventilation_cm5
```

Endpoint służy do pobierania centralnej historii, w szczególności dla zakresów przekraczających 30-dniowy lokalny bufor CM5.

Obsługiwane filtry:

- `metric`,
- `source`,
- `device_id`,
- `from`,
- `to`,
- `limit`.

### Rekomendacje AI

```text
GET /api/v1/recommendations/latest?source=ventilation_cm5
```

W Stage 1 endpoint zwraca brak dostępnej rekomendacji, dopóki integracja Qwen nie zostanie zaimplementowana i zwalidowana.

## SQLite

Stage 1 używa SQLite jako prostego backendu startowego Serwera AI.

Baza zawiera osobne struktury dla:

- odebranych paczek,
- pojedynczych próbek,
- pomiarów numerycznych,
- zdarzeń,
- przyszłych rekomendacji AI.

Włączony jest tryb WAL.

Docelowa migracja magazynu na NAS nie powinna zmieniać kontraktu HTTP z CM5.

## Uruchomienie na Ubuntu

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -e '.[dev]'
python -m ai_bridge
```

Domyślny port:

```text
8080
```

Dokumentacja OpenAPI po uruchomieniu:

```text
http://ADRES_SERWERA:8080/docs
```

Testy:

```bash
pytest
```

## Konfiguracja

Zmienne środowiskowe:

- `AI_BRIDGE_HOST` – domyślnie `0.0.0.0`,
- `AI_BRIDGE_PORT` – domyślnie `8080`,
- `AI_BRIDGE_DB` – domyślnie `data/ai_bridge.sqlite3`,
- `AI_BRIDGE_OLLAMA_URL` – domyślnie `http://127.0.0.1:11434`,
- `AI_BRIDGE_OLLAMA_MODEL` – domyślnie `qwen3.6:35b`,
- `AI_BRIDGE_ANALYSIS_ENABLED` – domyślnie `false`.

Analiza AI pozostaje celowo wyłączona domyślnie do czasu wdrożenia i zwalidowania kontraktu promptów, walidacji odpowiedzi oraz zapisu rekomendacji.

## Walidacja przed publikacją

Kod Stage 1 został sprawdzony przez:

- `python -m compileall`,
- zestaw testów `pytest`.

Wynik testów: **5/5 PASS**.

## Następny etap

Po uruchomieniu na rzeczywistym Ubuntu należy:

1. utworzyć środowisko Python i zainstalować zależności,
2. uruchomić AI Bridge lokalnie,
3. sprawdzić `/health` i OpenAPI,
4. wysłać testową paczkę HTTP,
5. sprawdzić zapis SQLite i historię,
6. dopiero później połączyć prawdziwy CM5,
7. następnie rozpocząć integrację z Ollamą/Qwen i 15-minutową agregację.
