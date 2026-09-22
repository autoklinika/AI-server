# AI Platform — D.6 preparation: production validation readiness

**Data:** 2026-09-22  
**Status:** READY FOR PRODUCTION VALIDATION  
**Implementation gate:** implementation ready for supervisor validation  
**Production gate:** NOT RUN — bez production validation, cutover ani live rollback.

## Zakres

Przygotowano kompletny kandydat Stage D do późniejszej walidacji. Nie oznaczamy
etapu COMPLETE. Nie zmieniono runtime schedulera, modeli, GPU, Ollama, ComfyUI,
Hermes ani infrastruktury. Stage E i kolejne pozostają poza zakresem.

Decyzję supervisora z 2026-09-22 zapisano w Component Contracts §20 oraz migration
plan/target architecture. Builder, RELEASE stamp i YAML manifest emitują:

```text
stage=D
phase=D.6
config_schema_version=3
migration_version=resource-manager-v2
resource_manager_contract_version=2
priority_class_contract_version=1
job_state_contract_version=1
provider_registry_schema_version=1
unified_admission_contract_version=1
compatibility_contract_version=1
```

YAML ma odpowiedniki w `release.contract_versions` i
`release.schema_versions.provider_registry`. Istniejące pięć kontraktów providerów
pozostaje w wersji 1; provider/model config bez zmian. Nie deklarujemy Platform API.
D.0 pozostaje historycznym kontraktem phase=D.0/schema=2/foundation-v1; nie
modyfikowano jego artefaktów ani Stage C recovery evidence.

## Tooling i procedury

- `validate_release_metadata.py`: offline porównanie RELEASE/generated YAML,
  wymaganych wersji, provider contracts, tożsamości wydania i SHA obu usług;
  odrzucenie braków, duplikatów i driftu. Parser obsługuje format emitowany przez
  builder, nie dowolny YAML. Builder i installed validator wywołują go; install
  i activate sprawdzają go dla D.6, zachowując historyczne ścieżki recovery.
- WVC validator: D.6 metadata, istniejące health/idle/policy/systemd gates,
  prawdziwy namespace `/clients/ventilation/api/chat`, priority 10,
  request/job correlation, completed wvc/reasoning, infrastructure i assignment.
  Nie wypisuje response body ani pełnego Environment. Nie zakłada, że CM5 nadal
  jest odłączony; live ingest jest osobnym, jawnym gate.
- Media validator: D.6 metadata, jawny `media-video` workload, Gateway health,
  zachowane preflight/idle/real render/ffprobe/PID guards. Unikalny katalog
  artefaktów jest zachowany. Surowy worker output nie jest kopiowany do logów
  walidacji. Nie zmienia to historycznego formatu prywatnych media job artifacts.
- `observe_validation.py`: tylko read-only health/count snapshot do późniejszych
  testów multiuser/media; bez source/prompt/lease token/raw queue. Opcjonalny
  `--require-idle` odrzuca zajęty albo niekompletny runtime snapshot.
- `validate_rollback_readiness.py`: offline weryfikacja checksumów kandydata i
  zachowanego rollback artifact, wymaganych metadata i źródeł obu usług;
  odrzucenie identycznych targetów, pustych checksumów, duplikatów i wyjścia
  ścieżki poza release. Nie wykonuje rollbacku ani nie dowodzi runtime health.
- [D.6 validation runbook](../../deploy/stage-d/D6_VALIDATION_RUNBOOK.md): WVC
  connected/disconnected, Telegram dwóch użytkowników i thread isolation,
  WAIT/START/FIFO/priority/cancel, Discord text/voice, `/foto`/`/wideo`, media
  crash limitations, matched helper/compiler/dispatcher inventory i pełny
  późniejszy cykl D.6 -> D.0 r2 -> D.6. Wszystkie live gates pozostają NOT RUN.

Nie osłabiono checksum, final-path venv, health/idle, previous-release ani
failure-recovery guardów. Dotychczasowy rollback script pozostaje bez zmian.
Build nie aktualizuje libexec: supervisor musi ustalić rzeczywiste zainstalowane
kopie i zachować dopasowany rollback zestawu klientów przed oknem produkcyjnym.
Brak takiego inventory blokuje live validation, nie został zastąpiony zgadywaniem
ścieżek ani nowym patchowaniem produktu Hermes.

## Automatyczna walidacja lokalna

Interpreter: `/home/harrypotter/AI-server/.venv/bin/python`, wyłącznie wykonanie
z `PYTHONPATH=src` tego worktree; bez instalacji lub zmiany zależności.

| Gate | Wynik |
|---|---|
| 31 nowych testów `test_stage_d6_preparation.py` | PASS |
| Suite poza czterema modułami TestClient | 621 PASS |
| Niezależne corestate tests | 3 PASS |
| Łącznie różne testy | 624 PASS |
| Bash syntax deploy/stage-a,b,c,d | PASS |
| Python compile nowych narzędzi/testów i embedded smoke Python | PASS |
| git diff --check | PASS |
| Pełny pytest | NIEUKOŃCZONY: TestClient startup hang, timeout 45 s |
| Pełny clean committed-source release build | NOT RUN — własność supervisora |
| Produkcyjne WVC/Telegram/Discord/media/rollback | NOT RUN |

Nowe testy obejmują rzeczywiste heredocs buildera (bez udawania pełnego builda),
stamp/YAML drift, wersje, checksum tampering/missing/path escape, sanitizację
obserwacji, mocked WVC metadata regression oraz połączone crash/TTL/priority/FIFO/
cancel przy concurrency 1, 2 i 4. Sprawdzono ścisłą granicę TTL, heartbeat queued
leases, kolejność dispatch i brak pozostałych slots/leases. Restart nowego registry
odrzuca stare lease ID i nie wznawia historii; nowe UUID są inne.

Istniejące suite D.1–D.5 zachowują pełną macierz semantic/legacy ordering,
non-preemption, queue full, HTTP/stream errors, cancellation queued/running/stream,
release-after-use, HTTP pin vs external TTL, cancellation races, media phases,
WVC routing, Telegram multiuser i Discord WAIT/START isolation. Crash/restart
są symulowane lokalnie; nie zabijano prawdziwych procesów. Zwolnienie lease przez
TTL nie anuluje remote ComfyUI renderu — to zachowany kontrakt D.4.

Polecenia odtwarzające:

```bash
PYTHONPATH=src python -m pytest tests/test_stage_d6_preparation.py tests/test_stage_d_foundation.py
PYTHONPATH=src python -m pytest --ignore=tests/test_gateway_resource_api.py --ignore=tests/test_analysis_delivery_api.py --ignore=tests/test_api.py --ignore=tests/test_corestate_extension.py
PYTHONPATH=src python -m pytest tests/test_corestate_extension.py -k 'not integrated_cm5_corestate_is_accepted_by_ingest'
PYTHONPATH=src timeout 45 python -m pytest -o faulthandler_timeout=15
```

Pełny run zatrzymał się przy `TestClient.__enter__` / anyio
`start_task_soon` / `run_sync_from_thread`, przed obsługą requestu. To znane
ograniczenie tej sesji opisane w D.1–D.5; nie zmieniano harnessu ani dependencies.
18 istniejących testów wymaga ponowienia w środowisku supervisora. Nowe testy
przeszły lokalnie. Wyników focused suite nie dodajemy ponownie do 624.

## Handoff

Supervisor: niezależna walidacja zmian, pełny pytest w działającym środowisku,
commit/CI i rzeczywisty clean-source release build, następnie osobno autoryzowane
okno produkcyjne według runbooka. Wymagane dowody: installed candidate, matched
client inventory/recovery, live WVC, multiuser delivery, media i rollback cycle.
Nie mylić offline readiness z produkcyjnym PASS.

Nie wykonano sudo, operacji systemd, odczytu credential/token files, zmian
`/opt`, `/var/lib`, sieci/secrets, produkcyjnego cutover/rollback, gh,
commit/push/PR/merge ani zmian workflows/.gitmodules. Nie usunięto recovery
artefaktów. Marker `.agent-result-D6PREP`: `READY_FOR_VALIDATION`.
