# AI Bridge / CM5 Telemetry — Stage 1 Final Report and Handoff

**Data:** 10.08.2026  
**Status:** PASS — etap operacyjnie zwalidowany  
**Repozytorium:** `autoklinika/AI-server`  
**Gałąź:** `agent/ai-bridge-stage1-clean-foundation`  
**Draft PR:** #2 `AI Bridge Stage 1 clean foundation`

## 1. Cel etapu

Celem Stage 1 było przygotowanie produkcyjnej granicy pomiędzy autonomicznym sterownikiem wentylacji CM5 a lokalnym Serwerem AI.

AI Bridge ma:

- odbierać telemetrię,
- walidować kontrakt danych,
- zapisywać dane transakcyjnie,
- zapewniać idempotencję,
- wystawiać health check,
- działać niezależnie od Ollamy/Qwena.

AI Bridge nie ma i nie może otrzymać endpointów sterujących wentylacją w ramach tej architektury.

## 2. Najważniejsza zasada bezpieczeństwa

```text
CM5 = sterowanie i bezpieczeństwo
AI Server = odbiór danych, storage, przygotowanie analizy, AI
Qwen = interpretacja i rekomendacje
```

Awaria AI Servera, PostgreSQL, Ollamy, Qwena lub przyszłego NAS nie może zatrzymać sterowania wentylacją.

AI Bridge deklaruje w health check:

```json
"control_commands_supported": false
```

## 3. Ostateczny tor Stage 1

```text
SEN55 slave 1 ─┐
               ├─ RS-485 → CM5 ventilation-core
SEN55 slave 2 ─┘
                         ↓
              wvc-telemetry-sync.service
                         ↓
               local SQLite / pending
                         ↓
                      LAN
                         ↓
      POST http://192.168.1.55:8080
      /api/v1/ventilation/telemetry/batches
                         ↓
                 ai-bridge.service
                         ↓
                    PostgreSQL
                         ↓
            ventilation_* RAW tables
```

AI Server: `192.168.1.55`.  
CM5 obserwowany w logu API: `192.168.1.64`.

## 4. Repozytorium i układ kodu

Kod AI Bridge znajduje się w:

```text
src/ai_bridge/
```

Struktura:

```text
src/ai_bridge/
├── __init__.py
├── __main__.py
├── main.py
├── settings.py
├── adapters/
│   └── ventilation/
│       └── schemas.py
├── api/
│   ├── app.py
│   └── ventilation.py
├── core/
│   └── errors.py
├── storage/
│   ├── database.py
│   ├── models.py
│   └── repository.py
└── ollama/
    └── client.py
```

Separacja modułów jest celowa: ingest, storage i przyszła analiza AI nie są jednym monolitycznym handlerem.

## 5. Konfiguracja aplikacji

`src/ai_bridge/settings.py` używa `pydantic-settings`.

Prefix zmiennych:

```text
AI_BRIDGE_
```

Najważniejsze parametry:

```text
AI_BRIDGE_HOST
AI_BRIDGE_PORT
AI_BRIDGE_LOG_LEVEL
AI_BRIDGE_DATABASE_URL
AI_BRIDGE_OLLAMA_URL
AI_BRIDGE_OLLAMA_MODEL
AI_BRIDGE_TELEMETRY_MAX_BODY_BYTES
```

Domyślne wartości aplikacji obejmują:

```text
host = 0.0.0.0
port = 8080
log_level = INFO
ollama_url = http://127.0.0.1:11434
ollama_model = qwen3.6:35b
telemetry_max_body_bytes = 1048576
```

SQLite jest tylko bezpiecznym backendem developerskim/testowym. Produkcja Stage 1 używa PostgreSQL przez `AI_BRIDGE_DATABASE_URL`.

## 6. Pliki i katalogi instalacji produkcyjnej

Kod wdrożony na AI Serverze:

```text
/opt/ai-bridge
```

Virtualenv produkcyjny:

```text
/opt/ai-bridge/.venv
```

Executable:

```text
/opt/ai-bridge/.venv/bin/ai-bridge
```

Konfiguracja produkcyjna:

```text
/etc/ai-bridge/ai-bridge.env
```

Katalog dopuszczony do zapisu przez hardening systemd:

```text
/var/lib/ai-bridge
```

Jednostka systemd:

```text
/etc/systemd/system/ai-bridge.service
```

W repozytorium wzorce znajdują się w:

```text
deploy/systemd/ai-bridge.service
deploy/ai-bridge.env.example
```

Hasło PostgreSQL pozostaje wyłącznie w konfiguracji hosta i nie jest commitowane do GitHub.

## 7. Systemd AI Bridge

Jednostka pracuje jako:

```text
User=harrypotter
Group=harrypotter
WorkingDirectory=/opt/ai-bridge
EnvironmentFile=/etc/ai-bridge/ai-bridge.env
```

Start:

```text
ExecStart=/opt/ai-bridge/.venv/bin/ai-bridge
```

Restart:

```text
Restart=on-failure
RestartSec=3
```

Hardening:

```text
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/var/lib/ai-bridge
```

Usługa jest:

```text
enabled
active (running)
```

Po pełnym restarcie AI Servera uruchamia się automatycznie bez terminala użytkownika.

## 8. HTTP API

AI Bridge nasłuchuje na:

```text
0.0.0.0:8080
```

W obecnej architekturze jest to usługa LAN, nie publiczny endpoint internetowy.

### Telemetria

```text
POST /api/v1/ventilation/telemetry/batches
```

Pełny adres używany przez CM5:

```text
http://192.168.1.55:8080/api/v1/ventilation/telemetry/batches
```

### Health

```text
GET /health
```

Zwalidowana odpowiedź:

```json
{
  "status": "ok",
  "service": "ai-bridge",
  "version": "0.1.0",
  "control_commands_supported": false,
  "components": {
    "database": "ok",
    "ollama": "not_checked"
  }
}
```

`ollama = not_checked` jest stanem celowym Stage 1. Ingest telemetrii nie zależy od modelu LLM.

## 9. Kontrakt batcha

Przykład logiczny:

```json
{
  "schema_version": 1,
  "source_id": "workshop-ventilation-cm5-01",
  "batch_id": "<stable UUID>",
  "created_at": "<timestamp>",
  "samples": [
    {
      "sample_id": "<stable UUID>",
      "sequence": 123,
      "captured_at": "<timestamp>",
      "metrics": {"...": "CoreState"}
    }
  ]
}
```

Limit kontraktowy Stage 1:

```text
max 500 samples / batch
max 1 MiB request body
```

## 10. Schemat danych wentylacji

Modele w:

```text
src/ai_bridge/adapters/ventilation/schemas.py
```

odwzorowują rzeczywisty `CoreState` CM5, a nie model hipotetyczny.

Obsługiwane tryby:

```text
STOP
MANUAL
FAULT
```

Nie dodano fikcyjnych `AUTO`, `BOOST`, RPM, CO2, airflow ani zmierzonych napięć, ponieważ nie są obecnie częścią rzeczywistego źródła danych.

## 11. PostgreSQL

Produkcja działa na PostgreSQL 18.x na AI Serverze.

Rola:

```text
ai_bridge
```

Baza:

```text
ai_bridge
```

Połączenie lokalne aplikacji:

```text
127.0.0.1:5432
```

URL jest przekazywany przez:

```text
AI_BRIDGE_DATABASE_URL
```

Hasło nie znajduje się w repozytorium.

## 12. Migracje Alembic

Konfiguracja:

```text
alembic.ini
alembic/env.py
```

Pierwsza migracja:

```text
alembic/versions/0001_ventilation_ingest.py
```

Migracja została wykonana na rzeczywistym Serwerze AI i utworzyła strukturę Stage 1.

## 13. Tabele centralnego storage

### `ventilation_ingest_batches`

Przechowuje metadane całych batchy:

```text
id
schema_version
source_id
batch_id
created_at
received_at
sample_count
payload_hash
```

Tożsamość batcha:

```text
(source_id, batch_id)
```

### `ventilation_telemetry_raw`

Przechowuje rzeczywiste próbki RAW:

```text
id
batch_record_id
source_id
sample_id
sequence
captured_at
received_at
metrics JSON
```

Tożsamość próbki:

```text
(source_id, sample_id)
```

## 14. Transakcyjność i ACK

Repozytorium storage:

```text
src/ai_bridge/storage/repository.py
```

Cały ingest odbywa się w sesji/transakcji bazy.

ACK jest zwracany po zakończeniu operacji storage. Dzięki temu CM5 nie oznacza lokalnego rekordu jako `synced` przed przyjęciem go przez centralny storage.

ACK zawiera:

```text
schema_version
source_id
batch_id
status=accepted
received
stored
duplicates
rejected
server_time
```

## 15. Idempotencja batcha

AI Bridge oblicza SHA-256 kanonicznego JSON całego batcha i zapisuje `payload_hash`.

Jeżeli ponownie pojawi się ten sam:

```text
source_id + batch_id
```

z tym samym payloadem, odpowiedź traktuje go jako retransmisję:

```text
stored = 0
duplicates = liczba próbek
```

Jeśli ten sam `source_id + batch_id` zostanie użyty dla innego payloadu, AI Bridge zgłasza konflikt tożsamości batcha zamiast nadpisać dane.

## 16. Idempotencja próbki

Przed zapisem nowego batcha AI Bridge sprawdza istniejące:

```text
source_id + sample_id
```

Jeżeli konkretna próbka była już zapisana w innym batchu, nie powstaje drugi rekord RAW.

Dzięki temu awaria pomiędzy commit a otrzymaniem ACK przez CM5 nie prowadzi do duplikowania pomiarów.

## 17. Odpowiedzialność CM5 za retry

AI Bridge nie utrzymuje sesji klienta ani kolejki dla CM5.

CM5 odpowiada za:

- lokalny durable pending,
- retry 5/15/30/60 s,
- zachowanie stabilnego `batch_id`,
- szybki catch-up po powrocie serwera.

AI Bridge odpowiada za idempotentne przyjęcie retransmisji.

Podział ten utrzymuje prostą granicę odpowiedzialności.

## 18. Zachowanie podczas awarii AI Bridge

Test rzeczywisty:

1. AI Bridge został zatrzymany.
2. CM5 otrzymywał `Connection refused`.
3. `ventilation-core` działał nadal normalnie.
4. SENSOR BUS pozostał zdrowy.
5. Oba SEN55 pozostały online.
6. CM5 gromadził lokalny pending.
7. Po powrocie AI Bridge CM5 automatycznie wykonał catch-up.

Zwalidowany zaległy batch:

```text
samples=34
stored=34
duplicates=0
```

## 19. Restart AI Servera

Wykonano pełny:

```text
sudo reboot
```

Po boot bez ręcznej ingerencji:

```text
ai-bridge.service = enabled / active
postgresql = active
```

AI Bridge uruchomił się automatycznie, `/health` wrócił, a kilka sekund później pojawiły się `POST ... 200 OK` z CM5.

Pierwsze dwa POST-y pojawiły się praktycznie bezpośrednio po starcie API, co odpowiada automatycznemu nadrobieniu próbek zapisanych przez CM5 podczas restartu serwera.

## 20. Restart CM5

Wykonano również pełny restart sterownika CM5.

Po boot:

- `ventilation-core.service` automatycznie active,
- `wvc-telemetry-sync.service` automatycznie active,
- oba SEN55 online,
- SENSOR BUS zdrowy,
- AI Bridge automatycznie zaczął ponownie odbierać `POST ... 200 OK`.

AI Server nie wymagał żadnej ingerencji przy restarcie źródła danych.

## 21. Testy Stage 1

AI Bridge:

```text
python -m compileall — PASS
pytest — 11/11 PASS
alembic upgrade head — PASS
PostgreSQL real host — PASS
```

Testy obejmują między innymi:

- retransmisję batcha,
- częściowe duplikaty,
- konflikt `batch_id`,
- wersjonowanie schematu,
- timestampy ze strefą czasową,
- odrzucanie nieznanych pól,
- brak endpointów sterujących,
- duplikaty `sample_id`,
- `sensor_bus=null`,
- limit requestu.

## 22. Instalacja hosta AI Server

Istotne elementy infrastruktury zwalidowane w projekcie:

```text
Ubuntu 26.04 LTS
Docker aktywny
Ollama 0.32.6 jako natywna usługa systemd
Qwen 3.6 35B
PostgreSQL 18.x
AI Bridge 0.1.0
```

Ollama działa lokalnie pod:

```text
http://127.0.0.1:11434
```

Qwen nie uczestniczy jeszcze w ingest ani ACK.

## 23. Granica Ollama/Qwen

Kod posiada osobny moduł:

```text
src/ai_bridge/ollama/client.py
```

ale endpoint telemetryczny nie wywołuje go.

Aktualny tor ingestu:

```text
CM5 → HTTP → validation → PostgreSQL → ACK
```

Nie:

```text
CM5 → Qwen → decyzja → sterowanie
```

Ta separacja jest obowiązkowa również w kolejnych etapach.

## 24. Przyszły NAS

Docelowy model storage został zaprojektowany tak, aby NAS mógł zostać dołączony bez zmiany protokołu CM5.

Obecnie:

```text
CM5 → AI Bridge → PostgreSQL na AI Serverze
```

Docelowo centralna warstwa danych może zostać przeniesiona lub zarchiwizowana na NAS.

CM5 nadal komunikuje się z AI Bridge, a nie bezpośrednio z systemem plików NAS.

Nie należy montować centralnego storage jako pojedynczego pliku SQLite używanego przez CM5 po SMB/NFS. Lokalny SQLite CM5 pozostaje lokalnym buforem awaryjnym.

`AI_BRIDGE_DATABASE_URL` zapewnia punkt konfiguracyjny dla przyszłej zmiany backendu/lokalizacji PostgreSQL bez przebudowy kontraktu HTTP.

## 25. Retencja i długoterminowa historia

CM5 zachowuje lokalnie 30 dni historii i pending.

Centralne archiwum ma zachowywać pełną szczegółową historię przez minimum pierwszy rok, aby zbudować baseline normalnej pracy warsztatu.

Później przewidziana jest retencja warstwowa:

- świeże RAW w pełnej rozdzielczości,
- starsze agregaty minutowe,
- agregaty 15-minutowe/godzinowe,
- ważne anomalie z zachowanym kontekstem.

## 26. Stan bezpieczeństwa po Stage 1

Potwierdzono praktycznie, że:

- zatrzymanie AI Bridge nie wpływa na CM5,
- restart AI Servera nie wpływa na sterowanie,
- restart CM5 sam odtwarza cały tor,
- PostgreSQL może być chwilowo niedostępny bez ścieżki do DAC,
- Qwen/Ollama są poza ścieżką ingestu,
- AI Bridge nie posiada API sterującego.

## 27. Stan końcowy Stage 1

Potwierdzony tor produkcyjny:

```text
SEN55 #1/#2
   ↓
CM5 ventilation-core
   ↓
wvc-telemetry-sync.service
   ↓
local SQLite durable queue
   ↓
LAN / HTTP
   ↓
ai-bridge.service
   ↓
PostgreSQL ai_bridge
```

Stage 1 jest operacyjnie zwalidowany po obu stronach, łącznie z retry, idempotencją, catch-up, systemd i restartami obu hostów.

## 28. Następny etap

Kolejny etap nie powinien zmieniać sprawdzonego ingestu.

Należy dodać nad nim warstwę analityczną:

1. wybór danych z PostgreSQL,
2. deterministyczne statystyki i agregacja w Python,
3. okna analityczne, docelowo około 15 minut,
4. przygotowanie kontrolowanego promptu,
5. przekazanie przygotowanych danych do Qwen,
6. odebranie analizy, anomalii i rekomendacji,
7. zapis wyników analitycznych,
8. brak automatycznego wykonywania rekomendacji przez CM5.

AI ma interpretować dane, a nie przejmować sterowanie.
