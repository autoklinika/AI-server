# AI Platform — Stage A Final Report

**Data:** 2026-09-19  
**Stage:** Recovery Baseline + Reproducible Release Foundation  
**Issue:** #31  
**Status:** PASS

## 1. Cel

Stage A miał wprowadzić bezpieczny recovery point i reprodukowalny model release bez zmiany funkcjonalności produkcyjnej, modelu AI, Hermesa ani backendów.

Cel został osiągnięty.

## 2. Recovery baseline

Recovery point:

`/srv/ai-data/platform/recovery/stage-a-20260919`

Zawiera m.in.:

- PostgreSQL `ai_bridge` dump,
- PostgreSQL globals,
- snapshot aktywnych konfiguracji `/etc/ai-*`,
- aktywne unity systemd,
- Hermes git bundle,
- pełny dirty patch Hermesa,
- aktywny Hermes state,
- spójne backupy SQLite,
- `SHA256SUMS`.

### PostgreSQL restore test

PASS.

Odtworzone dane:

- `ventilation_ingest_batches`: 38 232
- `ventilation_telemetry_raw`: 73 068
- `ventilation_analysis_runs`: 2 369

Testowa baza została po weryfikacji usunięta.

### Hermes

Zachowany stan:

- HEAD: `79445a496c86a19332ad786494b8384d2167e2d0`
- branch: `main`
- divergence: ahead 1 / behind 1
- dirty files:
  - `agent/turn_api_request.py`
  - `gateway/run_inbound.py`
  - `gateway/run_turn_runner.py`

`working-tree.patch` oraz pełny git bundle zostały zweryfikowane.

Cztery aktywne bazy SQLite zostały skopiowane przez SQLite backup API. Każda przeszła `PRAGMA integrity_check = ok`.

## 3. Reproducible production baseline

### AI Gateway

Produkcja była zgodna z:

`0e53bbc6f2fad703c46e00526d1bbecedb378438`

Kod `src` oraz `pyproject.toml` zostały zweryfikowane względem runtime.

### AI Bridge

Produkcja nie odpowiadała jednemu historycznemu commitowi.

Dokładny runtime został odtworzony wyłącznie z historii Git:

- base: `f993794a653981d7736484490e96f703c380aeb7`
- 5 kontrolowanych overlayów zapisanych w `deploy/stage-a/release-baseline.yaml`

Rekonstrukcja przeszła porównanie 1:1 z aktywnym `/opt/ai-bridge`.

Nie kopiujemy przypadkowego working tree runtime jako source of truth.

## 4. Dependency baseline

Python:

`3.14.4`

Osobne locki:

- `deploy/stage-a/locks/ai-bridge.requirements.txt`
- `deploy/stage-a/locks/ai-gateway.requirements.txt`

Zachowano dokładne wersje środowisk obu usług.

## 5. Release model

Wdrożono layout:

```text
/opt/ai-platform/releases/<release-id>/
/opt/ai-platform/current -> releases/<release-id>
```

Release zawiera:

- kod usług,
- własne venv,
- dependency locks,
- release manifest,
- build/release stamp,
- `SHA256SUMS`.

Builder:

`deploy/stage-a/build_release.sh`

## 6. Release'y Stage A

Zachowane:

- `stage-a-baseline-20260919-r0` — verified rollback point
- `stage-a-baseline-20260919-r1` — aktywny release

Aktualnie:

`/opt/ai-platform/current -> stage-a-baseline-20260919-r1`

## 7. systemd

Produkcja nie uruchamia już AI Bridge ani AI Gateway bezpośrednio z:

- `/opt/ai-bridge`
- `/opt/ai-gateway`

Effective runtime używa:

- `/opt/ai-platform/current/services/ai-bridge`
- `/opt/ai-platform/current/services/ai-gateway`

Dotyczy również `ai-bridge-analysis.service`.

Konfiguracje `/etc/ai-bridge` i `/etc/ai-gateway` pozostają bez zmian.

## 8. Testy

PASS:

- AI Bridge reconstruction
- AI Gateway source match
- dependency locks
- release imports
- równoległy Gateway smoke test
- równoległy Bridge smoke test
- r0 smoke test
- r1 smoke test
- cutover legacy -> r0
- upgrade r0 -> r1
- rollback r1 -> r0
- ponowny upgrade r0 -> r1
- effective systemd paths
- release SHA256 verification
- systemd health
- brak failed units

## 9. Brak zmiany funkcjonalności

Stage A nie zmienił:

- Qwen/modelu produkcyjnego,
- Ollamy,
- Hermesa,
- ComfyUI,
- funkcjonalności Telegram/Discord,
- zachowania WVC,
- API domenowego,
- scheduler semantics,
- security/network policy.

## 10. Cleanup

Usunięto tymczasowe logi i procesy smoke-testów.

Świadomie zachowano:

- r0 — rollback point,
- r1 — active release,
- recovery point Stage A,
- legacy `/opt/ai-bridge` i `/opt/ai-gateway`,
- stare worktree i historyczne backupy.

Legacy artifacts nie są jeszcze usuwane — ich cleanup nastąpi dopiero zgodnie z Migration Plan po dalszej stabilizacji.

## 11. Definition of Done

- verified backup: PASS
- PostgreSQL restore test: PASS
- Hermes diff safely captured: PASS
- release/build ID: PASS
- reproducible deployment from Git: PASS
- runtime independent from working checkout: PASS
- rollback tested: PASS
- health/smoke tests: PASS
- temporary Stage A artifacts cleaned: PASS
- production behavior preserved: PASS

**Stage A technical implementation: COMPLETE.**

Następny etap zgodnie z Migration Plan:

**Stage B / Etap 2 — Security hardening bez zmiany funkcji.**
