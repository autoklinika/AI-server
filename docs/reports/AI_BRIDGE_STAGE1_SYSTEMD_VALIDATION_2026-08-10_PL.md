# AI Bridge Stage 1 — walidacja usługi systemd na rzeczywistym Serwerze AI

**Data:** 10.08.2026  
**Status:** PASS — systemd + reboot obu hostów + automatyczny powrót telemetrii  
**Gałąź:** `agent/ai-bridge-stage1-clean-foundation`

## 1. Cel

Potwierdzić, że AI Bridge działa na docelowym Serwerze AI jako stała usługa systemowa, uruchamia się bez ręcznego terminala, poprawnie odbiera rzeczywistą telemetrię z CM5 zapisując ją do PostgreSQL oraz automatycznie wraca do pracy po restartach hostów po obu stronach toru.

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
POST /api/v1/ventilation/telemetry/batches HTTP/1.1 -> 200 OK
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

## 7. Powrót telemetrii po restarcie AI Servera

Już kilka sekund po starcie AI Bridge CM5 automatycznie wznowił transmisję bez ręcznej interwencji. Pierwsze dwa żądania pojawiły się w tej samej sekundzie po powrocie serwera, co jest zgodne z oczekiwanym catch-up próbek zgromadzonych lokalnie przez CM5 podczas restartu. Następnie tor wrócił do normalnego rytmu około 5 s.

Ponowny `/health` zwrócił `status=ok` i `database=ok`.

## 8. Test restartu całego CM5

Następnie zrestartowano cały CM5 przy pozostawionym działającym AI Serverze.

Po ponownym uruchomieniu CM5, bez ręcznego uruchamiania usług, potwierdzono:

```text
ventilation-core.service      -> enabled, active
wvc-telemetry-sync.service    -> enabled, active
```

`CoreState` po restarcie był zdrowy:

- `mode = STOP`,
- `hardware_ready = true`,
- `output_state_known = true`,
- brak aktywnych alarmów,
- SENSOR BUS `ready = true`,
- SENSOR BUS `worker_alive = true`,
- `worker_restarts = 0`,
- oba SEN55 `online = true`,
- oba SEN55 `usable = true`,
- oba SEN55 `measurement_valid = true`,
- brak błędów Modbus, pomiarowych i map-version.

Po stronie CM5 journal potwierdził kolejne:

```text
Telemetry batch synced ... samples=1 stored=1 duplicates=0
```

w normalnym rytmie około 5 s.

## 9. Potwierdzenie po stronie AI Bridge po restarcie CM5

AI Bridge nie wymagał żadnej ingerencji. Jego journal pokazał ciągły napływ świeżych żądań z ponownie uruchomionego CM5 `192.168.1.64`:

```text
12:21:07 POST /api/v1/ventilation/telemetry/batches -> 200 OK
12:21:12 POST /api/v1/ventilation/telemetry/batches -> 200 OK
12:21:17 POST /api/v1/ventilation/telemetry/batches -> 200 OK
...
12:22:44 POST /api/v1/ventilation/telemetry/batches -> 200 OK
```

Potwierdza to, że po restarcie CM5 cały tor wrócił samodzielnie:

```text
CM5 boot
  ↓
ventilation-core.service
  ↓
SENSOR BUS / 2× SEN55
  ↓
wvc-telemetry-sync.service
  ↓
LAN / HTTP
  ↓
ai-bridge.service
  ↓
PostgreSQL
```

## 10. Potwierdzony tor produkcyjny Stage 1

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

Obie strony działają bez ręcznie utrzymywanych procesów terminalowych oraz automatycznie wracają do komunikacji po restarcie dowolnego z dwóch hostów objętych Stage 1.

## 11. Granica bezpieczeństwa

Nadal obowiązuje i została zachowana architektura:

- CM5 jest jedynym sterownikiem wentylacji,
- AI Bridge przyjmuje wyłącznie telemetrię,
- `control_commands_supported = false`,
- awaria i restart AI Bridge nie wpływają na `ventilation-core`, DAC ani SENSOR BUS,
- podczas niedostępności AI Bridge CM5 zachowuje dane jako lokalny `pending`,
- po powrocie AI Bridge CM5 automatycznie wykonuje catch-up,
- restart CM5 nie wymaga ręcznego uruchamiania toru telemetrycznego,
- Qwen/Ollama nie znajdują się na ścieżce ingestu i ACK.

## 12. Wynik

**PASS — AI Bridge i CM5 działają poprawnie jako stałe usługi systemowe, automatycznie uruchamiają się po restartach swoich hostów i bez ręcznej interwencji odtwarzają pełny tor SEN55 → CM5 → AI Bridge → PostgreSQL.**

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
- restartu całego CM5,
- automatycznego powrotu toru telemetrycznego po obu restartach.

PR pozostaje Draft i nie powinien być merge'owany ani oznaczany Ready for Review bez wyraźnej decyzji użytkownika.
