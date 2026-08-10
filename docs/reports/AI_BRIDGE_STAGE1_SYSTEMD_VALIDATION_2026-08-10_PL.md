# AI Bridge Stage 1 — walidacja usługi systemd na rzeczywistym Serwerze AI

**Data:** 10.08.2026  
**Status:** PASS  
**Gałąź:** `agent/ai-bridge-stage1-clean-foundation`

## 1. Cel

Potwierdzić, że AI Bridge działa na docelowym Serwerze AI jako stała usługa systemowa, uruchamia się bez ręcznego terminala i poprawnie odbiera rzeczywistą telemetrię z CM5 zapisując ją do PostgreSQL.

## 2. Jednostka systemd

Zainstalowano i uruchomiono:

```text
ai-bridge.service
```

Stan:

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

## 6. Potwierdzony tor produkcyjny Stage 1

```text
SEN55 #1 + SEN55 #2
        ↓
ventilation-core na CM5
        ↓
wvc-telemetry-sync.service
        ↓
LAN / HTTP
        ↓
ai-bridge.service
        ↓
PostgreSQL ai_bridge
```

Obie strony działają bez ręcznie utrzymywanych procesów terminalowych.

## 7. Granica bezpieczeństwa

Nadal obowiązuje i została zachowana architektura:

- CM5 jest jedynym sterownikiem wentylacji,
- AI Bridge przyjmuje wyłącznie telemetrię,
- `control_commands_supported = false`,
- awaria AI Bridge nie wpływa na `ventilation-core`, DAC ani SENSOR BUS,
- podczas niedostępności AI Bridge CM5 zachowuje dane jako lokalny `pending`,
- po powrocie AI Bridge CM5 automatycznie wykonuje catch-up.

## 8. Wynik

**PASS — AI Bridge działa poprawnie jako stała usługa systemd na rzeczywistym Serwerze AI i odbiera telemetrię od stałej usługi CM5.**

Przed uznaniem całego wdrożenia Stage 1 za zamknięte operacyjnie zalecany jest jeszcze test restartu Serwera AI i potwierdzenie automatycznego startu `ai-bridge.service`, powrotu `/health` oraz automatycznego catch-up danych zgromadzonych przez CM5 podczas restartu.
