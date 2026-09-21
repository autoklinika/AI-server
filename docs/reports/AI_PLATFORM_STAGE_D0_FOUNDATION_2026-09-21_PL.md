# AI Platform — Stage D.0 Foundation Cleanup

**Data:** 2026-09-21  
**Branch:** `feat/stage-d0-foundation`  
**Issue:** #37  
**PR:** #38  
**Status:** READY TO MERGE — produkcja na D.0 r2; wszystkie exit criteria PASS

## 1. Cel

D.0 zamyka luki P1 wskazane w audycie po Stage C przed zmianami Resource Manager v2.

Zakres D.0:

- stabilne CI dla `main`,
- canonical release-managed systemd,
- Gateway jako domyślna ścieżka WVC analysis,
- Stage-D-compatible release/install/activate/rollback tooling,
- synchronizacja desired-state dokumentacji,
- pełna walidacja production cutover i recovery.

D.0 **nie zmienia** semantyki schedulera, modelu Qwen, GPU, Ollamy, ComfyUI ani Hermesa jako produktów.

## 2. Stan produkcji po walidacji

Aktywny runtime:

```text
release_id=stage-d0-foundation-20260921-r2
stage=D
phase=D.0
source_git_sha=3496f21249474d16c09a791db39afd321beb935c
config_schema_version=2
migration_version=stage-d-foundation-v1
provider_model_config_version=qwen36-hermes64k-gpu-20260919-v1
```

Runtime r2 pozostaje zbudowany z `3496f212...`.

Późniejsze commity branchu dotyczą wyłącznie walidatorów, hardeningu rollback tooling i dokumentacji. Nie podmieniano nimi aktywnego release r2.

Zweryfikowany rollback point:

```text
stage-c-provider-abstraction-20260921-r3
source_git_sha=cfe1b12ba5a35e2975ff942a2509ab2eaa3e21c5
```

## 3. Zmiany D.0

### 3.1 CI

Workflow `AI Platform CI` działa na:

- pull request do `main`,
- push do `main`.

Stabilny check/job:

```text
platform-ci
```

Gate obejmuje:

- bash syntax dla aktywnego deployment tooling,
- Python compile,
- provider/contract tests,
- D.0 invariant tests,
- pełny `pytest`,
- Stage D release build.

Końcowy rollback hardening przeszedł pełne CI na:

```text
d26e646b5277b3c83ee4a24cdd7e8db5e3413b1a
AI Platform CI #428 — PASS
```

### 3.2 Gateway-default policy

Desired state:

```text
AI_BRIDGE_ANALYSIS_USE_GATEWAY=true
```

Direct Ollama pozostaje wyłącznie jawnym recovery/debug compatibility mode.

Produkcja została zmigrowana przez odwracalny skrypt z prywatnym baseline:

```text
/var/lib/ai-platform/stage-d/gateway-policy-baseline
```

### 3.3 Canonical systemd

Canonical units używają:

```text
/opt/ai-platform/current/services/...
```

Usunięto historyczne override’y:

```text
ai-bridge.service.d/90-production-source.conf
ai-bridge-analysis.service.d/10-ai-gateway.conf
ai-bridge-analysis.service.d/90-production-source.conf
```

Zachowano właściwy Stage B LAN bind:

```text
ai-bridge.service.d/zz-lan-only.conf
AI_BRIDGE_HOST=192.168.1.55
```

Efektywny runtime AI Bridge i analysis nie zawiera już `/opt/ai-bridge/src` ani historycznego analysis `ExecStart`.

### 3.4 Release tooling

`deploy/stage-d/` zawiera wersjonowane:

- build,
- install bez aktywacji,
- validation,
- activation,
- rollback,
- canonical systemd install/restore,
- Gateway-default apply/restore,
- WVC/Gateway runtime validation,
- media runtime validation.

Rollback obsługuje:

1. emergency rollback do immediate previous release,
2. jawny known-good `RELEASE_ID`.

Po przełączeniu symlink rollback ma automatyczne przywrócenie source release, jeśli health-check nie przejdzie.

## 4. Produkcyjna walidacja

### 4.1 Build / install bez aktywacji

Release `stage-d0-foundation-20260921-r1`, a następnie poprawiony `r2`, zostały:

- zbudowane,
- zainstalowane do final path,
- zwalidowane przez checksums,
- zwalidowane przez final-path shebangs,
- zwalidowane przez provider imports,
- zwalidowane przez Stage30 standard + HQ/I2V preflight.

Install nie zmieniał aktywnego runtime ani PID-ów.

### 4.2 Cutover r2

Cutover do `stage-d0-foundation-20260921-r2` — PASS.

Po cutoverze:

- AI Bridge active,
- AI Gateway active,
- analysis timer active,
- Resource Manager 0 active / 0 queued / 0 leases,
- Hermes bez nieplanowanego restartu,
- ComfyUI bez nieplanowanego restartu.

### 4.3 WVC / Gateway / Qwen

WVC/CM5 był fizycznie odłączony podczas walidacji.

Dlatego brak świeżej telemetrii **nie był** używany jako kryterium awarii.

Zweryfikowano:

- AI Bridge health,
- obecność `POST /api/v1/ventilation/telemetry/batches` w OpenAPI,
- canonical analysis systemd,
- `analysis_use_gateway=true`,
- realny request przez Resource Manager do Qwena,
- source `ventilation-d0-validation`,
- priority `10`,
- powrót Resource Managera do `0/0/0`.

Po finalnej re-aktywacji r2:

```text
PASS: ventilation request executed through Gateway/Qwen
priority=10
wait_ms=0.028
```

### 4.4 Real media smoke

Realny Stage30 T2V został wykonany pod external Resource Manager lease:

```text
source=d0-media-smoke
priority=50
codec=h264
resolution=640x384
fps=24
frames=25
duration=1.0 s
```

Po renderze:

- Resource Manager idle,
- ComfyUI queue empty,
- AI Bridge PID bez zmiany,
- AI Gateway PID bez zmiany,
- Hermes PID bez zmiany,
- ComfyUI PID bez zmiany,
- test artifact usunięty.

### 4.5 Telegram `/wideo`

Realny user-path Telegram `/wideo` — PASS.

Film został wygenerowany i dostarczony do czatu.

Post-check:

```text
Resource Manager: 0 active / 0 queued / 0 leases
ComfyUI: queue_running=[] queue_pending=[]
AI Bridge PID:  83648 -> 83648
AI Gateway PID: 83623 -> 83623
Hermes PID:     30429 -> 30429
ComfyUI PID:    28119 -> 28119
```

Wszystkie usługi pozostały active.

## 5. Rollback validation

Wykonano pełny cykl:

```text
D.0 r2
  -> explicit rollback
Stage C r3
  -> health / idle / media preflight
  -> re-activate
D.0 r2
  -> WVC/Gateway/Qwen validation
  -> media preflight
  -> final idle checks
```

Wynik:

```text
STAGE C ROLLBACK VALIDATION: PASS
D.0 WVC/GATEWAY RUNTIME VALIDATION: PASS
D.0 ROLLBACK + REACTIVATION CYCLE: PASS
cycle_exit_code=0
D.0 ROLLBACK VALIDATION: PASS
```

Hermes i ComfyUI zachowały PID-y przez cały cykl.

Po finalnej re-aktywacji zapis rollbacku jest poprawny:

```text
previous=/opt/ai-platform/releases/stage-c-provider-abstraction-20260921-r3
target=/opt/ai-platform/releases/stage-d0-foundation-20260921-r2
```

## 6. Exit criteria

| Gate | Status |
|---|---|
| CI branch/PR | PASS |
| Stage D release build | PASS |
| install bez aktywacji | PASS |
| canonical systemd | PASS |
| Gateway-default production policy | PASS |
| production cutover | PASS |
| WVC platform path | PASS |
| real Gateway/Qwen ventilation request | PASS |
| real media render | PASS |
| Telegram `/wideo` user-path | PASS |
| Resource Manager idle after tests | PASS |
| ComfyUI queue idle after tests | PASS |
| rollback r2 -> Stage C r3 | PASS |
| re-activation Stage C r3 -> r2 | PASS |
| main required check / branch protection | PASS — `main-protection`, `platform-ci`, strict up-to-date |
| merge PR #38 | **PENDING** |

## 7. Pozostałe działania przed zamknięciem D.0

1. Merge PR #38 do `main` po finalnym zielonym `platform-ci`.
2. Potwierdzić push-to-main CI.
3. Zamknąć issue #37, jeśli nie zamknie się automatycznie przez PR.
4. Dopiero po tym rozpocząć D.1 — semantic priority classes.

## 8. Następny etap

**D.1 — semantic priority classes**.

Nie rozpoczynać D.1 przed merge D.0 do `main`.
