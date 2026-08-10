# AI Bridge Stage 1 — walidacja usługi systemd na rzeczywistym Serwerze AI

**Data:** 10.08.2026  
**Status:** PASS — systemd + reboot + automatyczny powrót telemetrii  
**Gałąź:** `agent/ai-bridge-stage1-clean-foundation`

## 1. Cel

Potwierdzić, że AI Bridge działa na docelowym Serwerze AI jako stała usługa systemowa, uruchamia się bez ręcznego terminala, poprawnie odbiera rzeczywistą telemetrię z CM5 zapisując ją do PostgreSQL oraz automatycznie wraca do pracy po restarcie całego Serwera AI.

## 2. Jednostka systemd

Zainstalowano i uruchomiono:

```text
ai-bridge.service
```

Stan przed restartem:

```text
Loaded: loaded (/etc/systemd/system/ai-bridge.service; enabled)
Active: active (running)
```

Proces:

```text
/opt/ai-bridge/.venv/bin/python3 /opt/ai-bridge/.venv/bin/ai-bridge
```

Usługa korzysta z:

- katalogu aplikacji `/opt/ai-bridge`,
- virtualenv `/opt/ai-bridge/.venv`,
- konfiguracji `/etc/ai-bridge/ai-bridge.env`,
- PostgreSQL jako backendu produkcyjnego.

## 3. Start aplikacji

Po uruchomieniu systemd log potwierdził:

```text
Started ai-bridge.service - AI Bridge local analytics service.
Started server process
Waiting for application startup.
Application startup complete.
Uvicorn running on http://0.0.0.0:8080
```

## 4. Health check

Lokalny test:

```text
GET http://127.0.0.1:8080/health
```

zwrócił:

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

Wynik potwierdza:

- poprawny start usługi,
- dostępność API,
- działające połączenie z PostgreSQL,
- brak endpointów sterujących,
- brak zależności ingestu od Ollamy/Qwena.

## 5. Rzeczywista telemetria CM5 po systemd

Po uruchomieniu AI Bridge jako usługi systemowej log potwierdził rzeczywiste żądania z CM5 `192.168.1.64`:

```text
192.168.1.64:43872 - "POST /api/v1/ventilation/telemetry/batches HTTP/1.1" 200 OK
192.168.1.64:43884 - "POST /api/v1/ventilation/telemetry/batches HTTP/1.1" 200 OK
```

Po stronie CM5 równocześnie działała stała usługa:

```text
wvc-telemetry-sync.service
```

z trwałą bazą:

```text
/var/lib/workshop-ventilation/telemetry.sqlite3
```

oraz prawidłowymi ACK:

```text
samples=1 stored=1 duplicates=0
```

## 6. Test restartu całego Serwera AI

Serwer AI został zrestartowany poleceniem `sudo reboot` przy pozostawionym działającym CM5.

Po ponownym uruchomieniu bez ręcznego startowania AI Bridge sprawdzono:

```text
systemctl is-enabled ai-bridge.service -> enabled
systemctl is-active ai-bridge.service  -> active
systemctl is-active postgresql         -> active
```

`ai-bridge.service` uruchomił się automatycznie:

```text
Active: active (running) since Mon 2026-08-10 12:12:55 CEST
Main PID: 2431 (ai-bridge)
```

Log z bieżącego bootu potwierdził pełny start aplikacji:

```text
Started ai-bridge.service - AI Bridge local analytics service.
Started server process [2431]
Waiting for application startup.
Application startup complete.
Uvicorn running on http://0.0.0.0:8080
```

## 7. Powrót telemetrii po restarcie

Już kilka sekund po starcie AI Bridge CM5 automatycznie wznowił transmisję bez żadnej ręcznej interwencji:

```text
12:12:58 192.168.1.64 - POST /api/v1/ventilation/telemetry/batches 200 OK
12:12:58 192.168.1.64 - POST /api/v1/ventilation/telemetry/batches 200 OK
12:13:03 192.168.1.64 - POST /api/v1/ventilation/telemetry/batches 200 OK
12:13:08 192.168.1.64 - POST /api/v1/ventilation/telemetry/batches 200 OK
12:13:13 192.168.1.64 - POST /api/v1/ventilation/telemetry/batches 200 OK
12:13:18 192.168.1.64 - POST /api/v1/ventilation/telemetry/batches 200 OK
12:13:23 192.168.1.64 - POST /api/v1/ventilation/telemetry/batches 200 OK
12:13:28 192.168.1.64 - POST /api/v1/ventilation/telemetry/batches 200 OK
```

Pierwsze dwa żądania nastąpiły w tej samej sekundzie po powrocie serwera, co jest zgodne z oczekiwanym automatycznym catch-up próbek zgromadzonych lokalnie przez CM5 podczas restartu AI Servera. Następnie tor wrócił do normalnego rytmu około 5 s.

Ponowny `/health` zwrócił `status=ok` i `database=ok`.

## 8. Potwierdzony tor produkcyjny Stage 1

```text
SEN55 #1 + SEN55 #2
        ↓
ventilation-core na CM5
        ↓
wvc-telemetry-sync.service
        ↓
local durable pending on CM5
        ↓
LAN / HTTP
        ↓
ai-bridge.service
        ↓
PostgreSQL ai_bridge
```

Obie strony działają bez ręcznie utrzymywanych procesów terminalowych oraz automatycznie wracają do komunikacji po restarcie AI Servera.

## 9. Granica bezpieczeństwa

Nadal obowiązuje i została zachowana architektura:

- CM5 jest jedynym sterownikiem wentylacji,
- AI Bridge przyjmuje wyłącznie telemetrię,
- `control_commands_supported = false`,
- awaria i restart AI Bridge nie wpływają na `ventilation-core`, DAC ani SENSOR BUS,
- podczas niedostępności AI Bridge CM5 zachowuje dane jako lokalny `pending`,
- po powrocie AI Bridge CM5 automatycznie wykonuje catch-up,
- Qwen/Ollama nie znajdują się na ścieżce ingestu i ACK.

## 10. Wynik

**PASS — AI Bridge działa poprawnie jako stała usługa systemd na rzeczywistym Serwerze AI, automatycznie uruchamia się po restarcie hosta, odzyskuje połączenie z PostgreSQL i przyjmuje backlog oraz bieżącą telemetrię z CM5 bez ręcznej interwencji.**

Stage 1 jest operacyjnie zwalidowany w zakresie:

- rzeczywistego CM5,
- dwóch SEN55,
- trwałego pending na CM5,
- pracy ciągłej,
- niedostępności AI Bridge,
- automatycznego catch-up,
- systemd na CM5,
- systemd na AI Serverze,
- restartu całego AI Servera,
- automatycznego powrotu toru telemetrycznego.

PR pozostaje Draft i nie powinien być merge'owany ani oznaczany Ready for Review bez wyraźnej decyzji użytkownika.
