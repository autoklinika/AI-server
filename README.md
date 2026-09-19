# AI Server

Lokalny Serwer AI dla wspólnej infrastruktury analitycznej **AI Bridge**.

Pierwszym obsługiwanym systemem jest Workshop Ventilation Controller. W przyszłości ta sama platforma może obsługiwać również inne adaptery domenowe, np. CRT.

## Nadrzędna zasada

> **CM5 steruje systemem. Python przygotowuje dane. Qwen interpretuje dane. AI doradza, ale nigdy nie steruje wentylacją.**

AI Server jest warstwą analityczną i integracyjną. Nie jest elementem wymaganym do bezpiecznego sterowania wentylacją.

## Aktualny stan hosta – 08.08.2026

- Ubuntu 26.04 LTS
- AMD Ryzen AI 9 HX 470, 12C/24T
- AMD Radeon 890M
- 128 GB RAM, z czego ok. 96 GB przeznaczone na UMA/iGPU
- NVMe 4 TB jako główny dysk systemowy
- SSH: port 22
- Cockpit: port 9090, `active` + `enabled`
- Docker 29.1.3, aktywny
- Ollama 0.32.6, `active` + `enabled`
- model `qwen3.6:35b`
- backend AMD ROCm/Vulkan
- wymuszone użycie iGPU przez `OLLAMA_IGPU_ENABLE=1`
- Vulkan włączony przez `OLLAMA_VULKAN=1`
- zwalidowane użycie modelu: ok. **4% CPU / 96% GPU**
- zwalidowany benchmark: ok. **28.68 tokenów/s**

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

## Aktualny kierunek prac

Audyt architektury i runtime v1.2 został zakończony 19.09.2026. Obecny system pozostaje produkcyjnie działający, ale dalszy rozwój jest prowadzony według **AI Platform Target Architecture v1**.

Pierwszym etapem migracji jest:

**Stage A — Recovery Baseline + Reproducible Release Foundation**

Celem Stage A nie jest zmiana modelu ani zachowania użytkowego. Etap ma wprowadzić zweryfikowany recovery point, release/build stamp, wersjonowany deployment i rollback, aby kolejne zmiany architektoniczne były odwracalne.

AI Bridge pozostaje aktywnym elementem obecnego runtime, ale nie jest już docelową nazwą całej platformy. Docelowa AI Platform ma obsługiwać wiele domen przez stabilne kontrakty i wymienne adaptery providerów.

## Bezpieczeństwo

Repozytorium nie może zawierać haseł, tokenów, kluczy ani innych sekretów. Dane uwierzytelniające do SSH, Cockpit i systemu operacyjnego pozostają wyłącznie na hoście/użytkowniku.
