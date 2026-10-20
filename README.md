# AI Server

Lokalny Serwer AI dla wspólnej infrastruktury analitycznej **AI Bridge**.

Pierwszym obsługiwanym systemem jest Workshop Ventilation Controller. W przyszłości ta sama platforma może obsługiwać również inne adaptery domenowe, np. CRT.

## Nadrzędna zasada

> **CM5 steruje systemem. Python przygotowuje dane. Qwen interpretuje dane. AI doradza, ale nigdy nie steruje wentylacją.**

AI Server jest warstwą analityczną i integracyjną. Nie jest elementem wymaganym do bezpiecznego sterowania wentylacją.

## Stan produkcji — 20.10.2026

- Jeden produkcyjny Gateway, jeden Resource Manager i jedna kolejka; cztery stany zasobu.
- Qwen `qwen3.8:27b-p4-64k-gpu-p511`, ComfyUI oraz Vision RADIO współpracują przez istniejący RM.
- Autostart i kolejność gotowości: **ComfyUI → Gateway/RM → Hermes**, odebrane po restarcie.
- Pełny rzeczywisty cykl Ollama → RADIO → ComfyUI → Ollama po restarcie: **PASS, 56,198 s**; końcowo RM IDLE, modele wyładowane, bez wykrytych błędów GPU.
- Telegram, Discord, PostgreSQL 18, Control Center i API: działają w odebranym zakresie.
- Stage K: kopia i weryfikacja z 20.10 o 14:21 CEST PASS; bieżąca kontrola po restarcie PASS. Ponowienia backupu co 5 minut, maksymalnie trzy próby; daily o 02:30.
- RADIO obsługuje na razie przypięty obraz kalibracyjny. Przyjmowanie zdjęć stanowiska jest osobnym etapem.
- Globalne `GPU_REUSE_SAFE=NOT_VERIFIED` i N1=`NOT_ADMITTED` pozostają jawne; jeden cykl nie jest testem długotrwałej stabilności.

[Stan repozytorium i mapa PR-ów](docs/REPOSITORY_STATUS_2026-10-20_PL.md) · [Odbiór po restarcie](docs/reports/COMFYUI_POST_REBOOT_ACCEPTANCE_2026-10-20_PL.md) · [Stage K](docs/reports/STAGE_K_BACKUP_RECOVERY_2026-10-20_PL.md)

Historyczna konfiguracja sprzętu i benchmark z sierpnia są zachowane w [raporcie hosta](docs/reports/AI_SERVER_HOST_CONFIGURATION_AND_GPU_VALIDATION_2026-08-08_PL.md).

## Zdalna administracja

Z Windows 11:

```powershell
ssh harrypotter@192.168.1.55
```

Cockpit:

```text
https://192.168.1.55:9090
```

RDP/xrdp nie są częścią docelowej konfiguracji hosta.

## Dokumentacja

### Architektura docelowa po audycie 2026-09-19

- [AI Platform — Architecture Index](docs/architecture/README.md)
- [AI Platform — Target Architecture v1](docs/architecture/AI_PLATFORM_TARGET_ARCHITECTURE_V1_PL.md)
- [AI Platform — Component Contracts v1](docs/architecture/AI_PLATFORM_COMPONENT_CONTRACTS_V1_PL.md)
- [AI Platform — Migration Plan v1](docs/architecture/AI_PLATFORM_MIGRATION_PLAN_V1_PL.md)
- [AI Server Architecture & Runtime Audit v1.2](docs/audit/AI_SERVER_ARCHITECTURE_RUNTIME_AUDIT_2026-09-19_PL.md)


- [Hermes: Discord voice — konfiguracja, diagnoza i odtworzenie 12.09.2026](docs/HERMES_DISCORD_VOICE_2026-09-12_PL.md)

### Architektura

- [ADR-002 – Strategia analizy danych przez AI](docs/ADR-002_AI_ANALYSIS_STRATEGY_PL.md)
- [ADR-003 – AI Bridge jako wspólna platforma pośrednicząca](docs/ADR-003_AI_BRIDGE_PLATFORM_ARCHITECTURE_PL.md)
- [ADR-004 – Przechowywanie i retencja danych telemetrycznych](docs/ADR-004_TELEMETRY_STORAGE_AND_RETENTION_PL.md)

### Kontrakty integracyjne

- [Ventilation Telemetry API v1](docs/VENTILATION_TELEMETRY_API_V1_PL.md)
- [Ventilation Telemetry Data Model v1](docs/VENTILATION_TELEMETRY_DATA_MODEL_V1_PL.md)

### Raporty

- [Raport inicjalizacji projektu](docs/AI_SERVER_PROJECT_INITIALIZATION_REPORT_PL.md)
- [Konfiguracja hosta, zdalny dostęp i walidacja GPU – 08.08.2026](docs/reports/AI_SERVER_HOST_CONFIGURATION_AND_GPU_VALIDATION_2026-08-08_PL.md)

## Zasady dalszych prac

Kod produkcyjnego Gateway w tej gałęzi odpowiada 239 plikom manifestu odebranego overlay `vision-radio-5d9d267489609ccb`. Stage O na hoście nadal wskazuje `stage-o-28e3ea214660`; porządkowanie repozytorium nie przełącza usług.

Eksperymenty N1–N5, SHARED/Multi-GPU i stare warianty Vision są zachowane w historycznych gałęziach i zamkniętych PR-ach. Nie należą do bieżącej implementacji produkcyjnej. Nowe funkcje wymagają osobnych zmian i właściwego odbioru.

`main` pozostaje chroniony: zmiany trafiają przez PR i zielony `platform-ci`. Historyczne raporty Stage D–O zachowują status i datę z czasu ich sporządzenia; bieżące potwierdzenia wskazano powyżej.

## Bezpieczeństwo

Repozytorium nie może zawierać haseł, tokenów, kluczy ani innych sekretów. Dane uwierzytelniające do SSH, Cockpit i systemu operacyjnego pozostają wyłącznie na hoście/użytkowniku.
