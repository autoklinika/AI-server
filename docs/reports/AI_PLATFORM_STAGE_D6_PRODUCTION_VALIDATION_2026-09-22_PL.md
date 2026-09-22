# AI Platform — Stage D.6 Production Validation

**Data:** 2026-09-22
**Release:** `stage-d-resource-manager-v2-20260922-r2`
**Source SHA:** `82d55f629f763c9352ad7c9e678e22eadb623639`
**Production validation:** PASS
**Stage D status:** **COMPLETE** — production gate PASS, PR #47 merged, pre-merge CI #451 PASS, post-merge CI #452 PASS.

## 1. Końcowy runtime

Aktywny release:

```text
/opt/ai-platform/releases/stage-d-resource-manager-v2-20260922-r2
```

Release contract:

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
provider_model_config_version=qwen36-hermes64k-gpu-20260919-v1
```

Końcowe PID / InvocationID:

```text
AI Bridge:
  PID=137996
  InvocationID=888a3eaed6ee48b38402d4ea5ea6b4f2

AI Gateway:
  PID=137984
  InvocationID=419c64656cbe45ffa4d2ebd2c84ce99c

Hermes:
  PID=138078
  InvocationID=fc38e2f2c4914adebdc5087426ffaebb

ComfyUI:
  PID=28119
  InvocationID=940c185ac7c04239878542c6b431653f
```

`ai-bridge-analysis.timer` został po walidacji przywrócony do `active`.

Końcowy Resource Manager / ComfyUI:

```json
{"active":0,"queued":0,"leases":0,"comfy_running":0,"comfy_pending":0,"gateway_healthy":true}
```

## 2. Matched client transition i rollback

Zweryfikowano pełny cykl:

```text
D.6 + D6 clients
-> restore PRE_D6 clients pod działającym D.6 Gateway
-> intentional Hermes restart
-> rollback release do D.0 r2
-> D.0 validation
-> activate D.6
-> apply D6 clients
-> intentional Hermes restart
-> pełna D.6 validation
```

Restore client bundle:

```text
Hermes PID: 132508 -> 136987
ComfyUI PID: 28119 -> 28119
```

Re-activation D.6 / apply client bundle:

```text
Hermes PID: 136987 -> 138078
ComfyUI PID: 28119 -> 28119
```

Końcowy bundle: `D6`.

Rollback release do `stage-d0-foundation-20260921-r2` przeszedł poprawnie po wcześniejszym restore klientów PRE_D6.

D.0 validation:

- AI Bridge active,
- AI Gateway active,
- Hermes active,
- ComfyUI active,
- Gateway healthy,
- Resource Manager 0/0/0,
- real WVC -> Gateway -> Qwen PASS.

Historyczny release D.0 r2 nie zawierał jeszcze `validate_wvc_gateway_runtime.sh`.
Do walidacji użyto historycznego validatora odpowiadającego D.0 semantics:

```text
commit=d26e646b5277b3c83ee4a24cdd7e8db5e3413b1a
blob=ae73699caddc195eb80faeb333552b8270d260c4
```

## 3. D.6 WVC / Gateway / Qwen

Realny request:

```text
namespace=/clients/ventilation/api/chat
priority=10
priority_class=infrastructure
domain=wvc
capability=reasoning
provider=ollama-local
model=qwen3.6:35b
```

Wynik:

```text
D.6 WVC/GATEWAY RUNTIME VALIDATION: PASS
Resource Manager precheck: 0/0/0
Resource Manager postcheck: 0/0/0
```

Live growth fizycznej telemetrii CM5 nie był częścią tego okna walidacji.

## 4. Real media

Realny Stage30 smoke:

```text
codec=h264
resolution=640x384
fps=24
frames=25
```

Wynik:

```text
D.6 MEDIA RUNTIME VALIDATION: PASS
```

PID-y przez cały smoke:

```text
AI Bridge: 137996 -> 137996
AI Gateway: 137984 -> 137984
Hermes: 138078 -> 138078
ComfyUI: 28119 -> 28119
```

Resource Manager i ComfyUI wróciły do idle po renderze.

## 5. Telegram / Discord user path

Operator potwierdził live:

```text
Telegram multiuser: PASS
WAIT/START user-path: PASS
cross-user delivery isolation: PASS
Telegram /foto: PASS
Telegram /wideo: PASS
Discord compatibility: PASS
```

Nie zaobserwowano crossed delivery ani utraty stabilności usług.

Live cancellation przez klienta nie był wykonywany w tym oknie. Status: `NOT RUN`.
Automatyczne testy cancellation pozostają wymaganym coverage; nie dodawano nowego
endpointu wyłącznie na potrzeby produkcyjnej walidacji.

## 6. Live priority / FIFO / non-preemption

Osobny live contention gate:

```text
17:26:39 active job=16 priority=50 interactive
17:26:45 queued job=17 priority=10 infrastructure/WVC
17:26:49 queued:
  job=17 priority=10 infrastructure/WVC
  job=18 priority=50 interactive
17:28:27 active job=17 priority=10; job=18 nadal queued
17:28:39 active job=18 priority=50
17:30:02 idle
```

Wynik:

```text
NON_PREEMPTION=PASS
WVC_PRIORITY_10_OVER_INTERACTIVE_50=PASS
QUEUE_ORDER=PASS
FINAL_IDLE=PASS
```

Aktywny interactive job 16 nie został wywłaszczony. Po jego zakończeniu WVC
priority 10 został uruchomiony przed oczekującym interactive priority 50.

Evidence lokalne operatora:

```text
~/agent-state/d6-production/d6-live-priority-order.log
```

## 7. Problemy wykryte podczas validation window

### 7.1 Hermes user-systemd z privileged wrappera

Supervisor wrappers wykonywane jako root nie mogą zakładać, że:

```text
runuser -u harrypotter -- systemctl --user ...
```

odziedziczy właściwy user bus.

Działający wzorzec:

```text
runuser -u harrypotter -- env \
  HOME=/home/harrypotter \
  XDG_RUNTIME_DIR=/run/user/<uid> \
  systemctl --user ...
```

Jawne ustawienie `DBUS_SESSION_BUS_ADDRESS` okazało się w tym oknie zbędne i
powodowało błąd połączenia. Supervisor wrappers zostały lokalnie poprawione do
wariantu z `XDG_RUNTIME_DIR`. Wersjonowany `d6_client_bundle.py` już używa
właściwego mechanizmu `runuser + XDG_RUNTIME_DIR`.

### 7.2 D.0 validator packaging

Rollback wrapper początkowo zakładał istnienie:

```text
D0/services/ai-bridge/deploy/stage-d/validate_wvc_gateway_runtime.sh
```

Plik nie występuje w historycznym D.0 r2. Sam rollback release i restore klientów
przeszły poprawnie; `rc=127` dotyczył wyłącznie błędnego post-validation wrappera.

Runbook powinien jawnie wskazywać użycie zweryfikowanego historycznego validatora
odpowiadającego danemu recovery release, jeżeli validator został dodany po buildzie.

## 8. Evidence

Operator evidence:

```text
~/agent-state/d6-production/failed-gate-rollback-fixed.log
~/agent-state/d6-production/d6-phase1-reactivation.log
~/agent-state/d6-production/d6-live-priority-order.log
```

Recovery snapshot pozostaje zachowany i nie był usuwany.

## 9. Wynik

```text
D6_RELEASE_CUTOVER=PASS
D6_CLIENT_APPLY=PASS
D6_CLIENT_RESTORE=PASS
D6_TO_D0_ROLLBACK=PASS
D0_RUNTIME_VALIDATION=PASS
D0_TO_D6_REACTIVATION=PASS
WVC_GATEWAY_QWEN=PASS
REAL_MEDIA=PASS
TELEGRAM_MULTIUSER=PASS
TELEGRAM_FOTO=PASS
TELEGRAM_WIDEO=PASS
DISCORD=PASS
LIVE_PRIORITY=PASS
FINAL_RUNTIME_HEALTH=PASS
LIVE_CLIENT_CANCELLATION=NOT_RUN
```

Stage D.6 production gate jest zaliczony.

## 10. Formalne zamknięcie Stage D

Desired state został zapisany w repo i przeszedł governance:

```text
PR #47: MERGED
merge_commit=62f00ab2a1aade2be9cc86d69e068647652d5a27
pre_merge_ci=#451 PASS
post_merge_ci=#452 PASS
```

Pełny test suite oraz `Validate Stage D release build` przeszły również w post-merge CI.

**Stage D = COMPLETE.**
