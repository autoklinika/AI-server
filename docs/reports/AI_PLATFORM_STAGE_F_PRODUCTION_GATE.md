# Stage F production gate — 2026-09-23

Status: **Production candidate/rollback/reactivation gate PASS**; **COMPLETE**, including final CI/merge and post-merge CI. Candidate `stage-f-d8f68cadd953`, source
`d8f68cadd95372b5a9adc75ef6450719af437850`. Reviewed in
[PR #63](https://github.com/autoklinika/AI-server/pull/63).

> Subsequent operational state: G final validation hit a new MES failure on the
> same boot. F was restored with ingress paused. This completed F gate remains
> historical evidence, not a claim of current GPU health; see the
> [G incident report](AI_PLATFORM_STAGE_G_PRODUCTION_GATE.md).

## Evidence boundary

Messaging E2E is **SYNTHETIC/INTERNAL**: two independent Telegram-like contexts and
two Discord-like contexts use installed-plugin discovery, real Hermes streaming
turn execution, request/job correlation, WAIT→START, admitted prompt compilation,
production dispatchers/renderers, attachments and artifact checks. The harness
records deliveries internally. Separate compatibility checks exercise configured
outbound Telegram/Discord delivery. **Real external inbound Telegram/Discord
transport remains DEFERRED/NOT TESTED**, never PASS. Historical D.6 results are not
fresh F evidence.

## Root cause and repair

The prior hang began seconds after heavy ComfyUI rendering while Ollama retained a
model with `OLLAMA_KEEP_ALIVE=-1`. The architecture had equated completed inference
with released GPU memory. Guarded validation additionally exposed a legacy image
renderer that independently preloaded Qwen after rendering. Both paths could
violate exclusive shared-GPU residency. The timing identifies overlapping
residency as the primary repair target, not a proven GPU driver failure mechanism.
**No GPU driver fix is claimed.** The operator reboot restored ROCm gfx1150 and
working inference/unload before this repair was deployed.

Resource Manager now drains in-flight LLM work and holds exclusive media ownership,
explicitly unloads Ollama residents with `keep_alive=0`, and requires empty `/api/ps`
before authorizing ComfyUI. Cleanup requires empty Comfy queues, zero loaded models,
acknowledged `/free` flags, and bounded Torch workspace. A persistent failure latch
keeps admission closed across Gateway restarts. TTL/release cannot revoke an
external GPU owner. Idempotent cleanup retries handle a missed Comfy worker wakeup;
HTTP success or a fixed sleep never substitutes for readback.

Versioned image renderers require a live external-use token and cannot preload
Ollama independently. Prompt compilers are bounded to 512 tokens without reasoning.
The read-only Comfy custom-node route is pinned to source
`ace9172e95038ac25015c419713aa7755f739034`. Normal handoffs restart neither provider;
deployment restarts Comfy only to install/remove the extension. Ollama remained
PID **3054**, started **2026-09-23 08:41:16 CEST**, throughout the acceptance cycle.

Comfy cleanup retained 32 MiB after image work and 34 MiB after video work. Production
allows at most 64 MiB per device for HIP workspace/small buffers, independently of
mandatory zero loaded-model count and cleared cleanup flags. This does not claim
zero process/context GPU memory. See the [architecture](../architecture/GPU_RESIDENCY.md)
and [recovery policy](../runbooks/GPU_RESIDENCY_RECOVERY.md).

## Validation

| Check | Result |
|---|---|
| Full local suite | 799 passed, 2 dependency deprecation warnings |
| Candidate source CI | PASS, [run 35834044842](https://github.com/autoklinika/AI-server/actions/runs/35834044842) |
| Immutable build/install and cutover | PASS |
| Initial short Qwen, Platform API, WVC compatibility, Hermes | PASS |
| Candidate internal chat/queue/media E2E | PASS: image, video, image edit, video; all prompt compilers used Qwen |
| Candidate cleanup and subsequent Qwen load/inference | PASS |
| Planned E rollback and bounded rollback smoke | PASS |
| F reactivation | PASS |
| Final independent full smoke | PASS: four media jobs, cleanup and subsequent Qwen inference |
| Kernel cursor guards across all smoke phases | PASS: no new MES/ring/reset/timeout faults |
| Production finalize | PASS |
| Final documentation CI | PASS, [35837126605](https://github.com/autoklinika/AI-server/actions/runs/35837126605) |
| PR merge | `245caef37032ad637324ec99f171ee4492f62d5f` |
| Post-merge CI | PASS, [35837338807](https://github.com/autoklinika/AI-server/actions/runs/35837338807) |
| External inbound Telegram/Discord | DEFERRED/NOT TESTED |

The candidate observer collected 351 samples, including 259 stable media-ownership
samples; none contained an Ollama resident. Observations supplement the controller's
mandatory transition checks. The final observer collected 352 samples, including
264 stable media-ownership samples, also with zero Ollama residents. Polling alone is not treated as proof of race safety.
Tests cover concurrent admission/drain, failure/timeout/cancellation, persistent
blocking, heartbeat/release races, duplicate cleanup, scoped media tokens, missing
Comfy evidence, unexpected model reload and rollback without candidate health.

Rollback restored `stage-e-38fff86f7704` and exact archived source/config/client
bytes, modes and ownership. It used verified E Python plus the reviewed controller;
it did not depend on the failed candidate's health or executable environment.
External ingress remained paused during legacy E verification, and no heavy media
ran under E because E lacks this residency boundary. Reactivation restored F
integration and ingress. New conversation/domain history was not overwritten.
D.0, D.6 and E recovery artifacts remain preserved.

## Evidence and failed attempts

Private immutable state and kernel cursor evidence are under
`/var/lib/ai-platform/stage-f/d8f68cadd95372b5a9adc75ef6450719af437850/`.
The phase records are `candidate-smoke.json`, `rollback-smoke.json`, `final-smoke.json`
and `complete.json`; each smoke points to its immutable evidence directory.
Sanitized local execution/observer logs are under
`/home/harrypotter/agent-state/manual-eh/f-residency-*d8f68ca*`.
Credentials, conversation content and private snapshots are not published.

Earlier attempts remain failed evidence: legacy independent Qwen preload,
unbounded prompt compilation, an overly strict allocator ceiling, and a missed
Comfy cleanup wakeup. They prompted architectural fixes and tests, not manual
acceptance overrides. No failed render/cleanup was counted as PASS. The
[pre-reboot incident report](AI_PLATFORM_STAGE_F_GPU_BLOCKER_2026-09-23.md) is
historical and superseded by this post-reboot validation record.
