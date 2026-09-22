# D.6 production validation handoff

Status: **PRODUCTION VALIDATION EXECUTED — PASS (2026-09-22)**. The preparation
sections below remain the original handoff; final evidence is linked at the end.
Only the supervisor/operator can schedule and authorize the production window.
No command in this document grants permission to change production.

## Offline gate and release identity

Run the full `PYTHONPATH=src python -m pytest` suite. The focused regression set is:

```bash
PYTHONPATH=src python -m pytest tests/test_gateway_scheduler.py tests/test_gateway_priority_classes.py tests/test_gateway_jobs.py tests/test_gateway_resource_leases.py tests/test_gateway_unified_admission.py tests/test_compatibility_migration.py tests/test_media_admission.py tests/test_stage_d_foundation.py tests/test_stage_d6_preparation.py tests/test_stage_d6_client_bundle.py
```

Coverage: numeric/semantic priority, equal-priority FIFO, queue full,
non-preemption, concurrency 1/2/4, queued/running/stream cancellation,
HTTP/stream errors, worker heartbeat loss/TTL boundary, external-use expiry,
HTTP pin protection, deferred release, cancellation races, WVC namespace,
Telegram multiuser/Discord WAIT/START targeting, media lease phases and privacy.
A crashed Gateway loses in-memory jobs; there is no durable resume contract.
A crashed worker's TTL frees admission but does **not** stop a remote render.
Never induce a production crash to substitute for these automated cases.

The supervisor commits and builds clean source with `build_release.sh`.
Do not bypass its clean-tree check or claim that heredoc tests built a release.
Both services must have the same source SHA. Run offline checks against exported
artifacts (these tools neither contact services nor activate anything):

```bash
python3 deploy/stage-d/validate_release_metadata.py "$CANDIDATE"
python3 deploy/stage-d/validate_rollback_readiness.py "$CANDIDATE" "$ROLLBACK"
```

Expected candidate: D / D.6 / config schema 3 / resource-manager-v2;
Resource Manager 2; priority, JobState, provider registry, unified admission and
compatibility each 1. Provider contracts remain 1. The metadata validator accepts
the builder's emitted YAML subset, not arbitrary YAML formatting.

## Inventory before the production window

Record release IDs/SHA/checksums for candidate and known-good D.0 r2. Preserve
Stage C r3, previous-release state, existing recovery snapshots and Hermes patch
capture. Never overwrite or delete them. Record timer state, service active
states and nonzero PIDs (Bridge, Gateway, Hermes, ComfyUI), current symlink and
health, plus wrapper/helper hashes. Keep evidence in a private operator directory;
no env dumps, credentials, raw prompts, raw Gateway status or ComfyUI queue bodies.

The real inventory identified exactly five active client replacements:

| Installed path | D.6 source under `services/ai-bridge/` |
|---|---|
| `/usr/local/bin/hermes-foto-dispatch` | `tools/local_image/hermes_foto_dispatch_global.py` |
| `/usr/local/libexec/ai-server/hermes_resource_queue.py` | `tools/hermes_resource_queue.py` |
| `/usr/local/libexec/ai-server/hermes_foto_prompt_compiler.py` | `tools/local_image/hermes_foto_prompt_compiler.py` |
| `/usr/local/libexec/ai-server/hermes_video_dispatch.py` | `tools/local_video/hermes_video_dispatch_global.py` |
| `/usr/local/libexec/ai-server/qwen_prompt_compiler.py` | `tools/local_video/qwen_prompt_compiler.py` |

The immutable original snapshot is
`/srv/ai-data/platform/recovery/stage-d6-resource-manager-v2-20260922-r1-clients`.
The original TSV manifest has exactly the columns `state`, `installed_sha256`,
`candidate_sha256`, `installed_path`, `candidate_path`. Supply its actual path
inside that snapshot as `MANIFEST`; do not invent or rewrite its filename/content.
Restore bytes are `SNAPSHOT/${installed_path#/}`, checked against
`installed_sha256`. Original backup stat supplies mode/uid/gid. Sanitized handoff
copies and `recovery-contract.tsv` are implementation evidence only, never
production restore sources. r1 candidate hashes/paths do not bind a future r2.

Do not update `generate_ltx23.py`, `generate_ltx23_stage29.py`, or
`generate_ltx23_base.py` in libexec, even though they have historical DIFF rows.
They remain recovery evidence until Stage H. The identical, release-managed
`/usr/local/bin/generate-video-ltx23` wrapper needs no replacement.
The packaged ComfyUI adapter follows the release. No Hermes source patch,
product/model/GPU configuration or additional client files are changed.

Install without activation and use `validate_installed_release.sh` only in the
later authorized window. It retains checksum, final-path, preflight and unchanged
runtime checks. Existing installation/cutover scripts require operator privileges;
the preparation agent must not execute them. Preserve all health/idle guards.
Activation must have a healthy Bridge/Gateway, no active analysis, Resource Manager
0/0/0 and empty ComfyUI queue. Use the existing guarded activation procedure;
never force a switch around a failed guard.

## Matched client transition (controlled executor only)

`d6_client_bundle.py apply|restore` is versioned Stage D tooling. Execute only
in a separately authorized, privileged production window; it never invokes sudo
or activates a release. Keep ingress and analysis quiesced for the entire window;
`--quiesced` records this executor precondition. Point-in-time idle guards do not
lock admission. Do not resume smoke/user traffic until the command succeeds.
Concurrent bundle invocations are rejected through an exclusive executor lock.

After activating D.6 and verifying Gateway health/idle, the controlled executor
can apply the bundle using these arguments (this is not authorization to run it):

```text
python3 deploy/stage-d/d6_client_bundle.py apply \
  --release /opt/ai-platform/releases/<D6-ID> \
  --manifest <original-manifest-path-inside-snapshot> \
  --hermes-user <existing-Hermes-service-owner> --quiesced
```

Use `restore` with the same D.6 release and manifest to restore the pre-D.6
bundle. Both actions require the matching D.6 current symlink and running Gateway
working directory, validated D.6 metadata/checksums and both packaged client source
copies, complete backup validation, a complete known installed bundle, healthy/idle
Resource Manager and empty ComfyUI queues. Sources absent from release checksums
are rejected. Atomic per-file replacements use root ownership and 0755 for the two
dispatchers, 0644 for helpers/compilers; restore uses preserved backup metadata.

An **intentional Hermes restart is required after each client-bundle transition**:
`patch_hermes_global_resource_queue.py` caches the helper in `sys.modules` as
`_ai_server_resource_queue`. Changing bytes alone does not reload that behavior.
The tool restarts only `hermes-gateway.service` in its existing user's manager,
waits up to 90 seconds for a changed service identity and fresh gateway-state
confirmation of running + Telegram connected + API connected, then verifies
Gateway health/idle and unchanged ComfyUI PID/invocation. It reads no credentials
and prints no raw gateway-state, prompt, status or queue content.

Take a **new Hermes PID baseline after each successful intentional transition**.
Hermes must remain stable during every subsequent smoke/validation phase.
ComfyUI PID/invocation must remain unchanged throughout the entire cycle.
Bridge/Gateway may restart only during authorized release switching.

Caught write/restart/post-check failures attempt to restore the complete entry
bundle and intentionally restart Hermes again, with the same health/idle and
ComfyUI guards. A recovered failure remains FAIL. If those guards fail, automatic
recovery stops: keep D.6 active, preserve the original snapshot and installed-file
inventory, and hand control to the executor. Never switch to D.0 or resume traffic
with uncertain/mixed clients. SIGINT/SIGTERM use this failure path; power loss or
SIGKILL can leave a partial bundle requiring controlled manual recovery from the
validated old/new sources. The normal command deliberately rejects unknown/mixed
bundles instead of blessing them. No recovery artifacts are deleted.

## WVC regression

After authorized candidate activation and successful client-bundle apply, run
`validate_wvc_gateway_runtime.sh`.
It verifies D.6 metadata, canonical analysis configuration, Gateway policy, Bridge
health and ingest OpenAPI contract, healthy/idle Gateway, real Qwen request through
`/clients/ventilation/api/chat` with priority 10, then idle recovery.
Record PASS/FAIL and job ID/priority/wait only, never response/prompt content.
This synthetic check does not prove live telemetry ingestion or domain analysis.

Record CM5 connected/disconnected explicitly. If disconnected, mark live ingest
NOT RUN (expected), preserve history, and do not synthesize production telemetry.
If connected, observe two genuine batches through the existing WVC interface:
HTTP success, advancing timestamps/counts without duplicates and normal advisory
analysis delivery. Verify no control command is issued. Compare with pre-window
baseline. Missing fresh telemetry must not be represented as a synthetic PASS.
Do not implement the later Stage G freshness policy here.

## Telegram multiuser and Discord compatibility

Use two consenting test users in distinct chats/threads and synthetic non-sensitive
requests. Take `python3 deploy/stage-d/observe_validation.py --require-idle`
before and after the scenario; during it use the same tool without `--require-idle`.
It prints only counts/health, with no prompts, source strings or lease tokens.
Record service PIDs before/after each phase and verify unchanged, active services,
using the new Hermes baseline from the last intentional bundle transition.

1. User A starts a sufficiently long normal chat; user B queues another chat.
   Confirm one active reservation at default concurrency 1 and no overlap.
2. Queue a WVC regression request while A holds admission. A is not preempted;
   queued WVC priority 10 precedes interactive 50. Equal-priority chat requests
   start FIFO. Correlate sanitized job IDs/order locally, not conversation content.
3. B gets existing WAIT once, then START once in B's original chat/thread.
   Immediate admission does not emit a spurious WAIT. Responses must not cross
   users/sessions/threads; an ACK alone is not success.
4. Cancel a queued request through the existing client mechanism, then a running
   request where supported. Confirm no leaked lease/slot and subsequent progress.
   If the client has no cancellation control, record that live case NOT RUN and
   retain the automated cancellation gate; do not invent a new endpoint.
5. Exercise Discord text and voice callback targeting as a compatibility check.
6. Exercise Telegram `/foto` and `/wideo` delivery to the requesting thread.
   Record artifact hash/type and delivery success, without copying user content.

Any crossed delivery, duplicate notices, priority regression or leaked reservation
fails the gate. Missing participating users leaves multiuser NOT RUN, not PASS.

## Real media smoke

Run `validate_media_runtime.sh` in the authorized window. It verifies candidate
metadata and release-managed wrapper, preflight, health/idle, `media-video` lease,
real Stage30 render, H.264 640x384 / 24 fps / 25 frames, lease held throughout,
idle queues afterward and unchanged Bridge/Gateway/Hermes/ComfyUI PIDs within
that smoke phase (Hermes baseline taken after the bundle transition).
The unique `/tmp/stage-d6-media-smoke.*` directory is preserved as evidence.
Do not print raw worker output. Verify the installed helper/dispatcher performs
D.4 external-use claims; a successful MP4 alone does not prove admission coverage.
Verify `/foto` separately through the user path (no new workflow/model).

If a worker times out/crashes, treat the smoke as FAIL; inspect counts and actual
ComfyUI activity. Lease expiry is not render cancellation. Do not run another
workload or switch releases until the remote queue is confirmed idle. Preserve
artifacts and use the established operator recovery procedure.

## Rollback validation in the later authorized window

Offline artifact readiness is not a live rollback PASS. Record all gates for:

`D.6 candidate -> known-good D.0 r2 -> same D.6 candidate`.

The required order is deliberate: D.6 Gateway supports old clients; historical
D.0 Gateway must never receive new D.6 clients.

Rollback:

1. Start with D.6 release + D.6 clients; quiesce traffic and verify idle.
2. Run `d6_client_bundle.py restore` **while D.6 Gateway remains active**.
3. Require intentional Hermes restart, fresh Telegram/API connectivity, new
   Hermes PID baseline, Gateway health/idle and unchanged ComfyUI.
4. Only after successful restore, use `rollback_release.sh <known-good-D0-id>`.
5. Validate D.0 with the exact preserved pre-D.6 clients.

Re-activation:

1. Start with D.0 release + pre-D.6 clients; quiesce traffic and verify idle.
2. Activate D.6 release first; verify D.6 Gateway health/idle.
3. Run `d6_client_bundle.py apply` against that active D.6 release.
4. Require intentional Hermes restart and health; take a new Hermes PID baseline.
5. Run full D.6 validation.

The standalone historical release scripts do not install or restore clients;
never use them to skip this ordering. Preserve their checksum/idle/health checks
and failure traps restoring the source release. An activation failure before
client apply leaves old clients compatible with either release. If release rollback
fails after successful client restore, recovered D.6 Gateway remains compatible
with old clients. Do not delete snapshots after reactivation.

At each side: verify symlink/RELEASE, expected metadata (historical D.0 is valid),
checksums, healthy Bridge/Gateway, Resource Manager 0/0/0, empty ComfyUI queues,
canonical units, expected timer state, media preflight, WVC and user-path smoke.
Use historical validators from the rollback release for D.0; current D.6 validators
intentionally reject D.0. Hermes PID is expected to change across intentional client-bundle transitions;
it must remain stable within each validation phase using its new baseline.
ComfyUI must remain unchanged across the whole cycle; Bridge/Gateway restarts
are expected only within the authorized release switch procedure.
After reactivation rerun D.6 metadata/WVC/media/multiuser gates and verify the
previous-release record identifies the intended recovery target.

Record failure and recovery outcome separately if a switch fails. Never mark a
failed attempt PASS merely because the automatic source restore ran. Supervisor
owns final production evidence, CI/merge and any eventual COMPLETE designation.

## Production validation result — 2026-09-22

D.6 r2 production validation została wykonana. Cutover, matched client
restore/apply, D.6 -> D.0 r2 -> D.6 rollback cycle, WVC/Qwen, media,
Telegram multiuser, `/foto`, `/wideo`, Discord i live priority/non-preemption
zakończyły się PASS. Live client cancellation: NOT RUN; automated coverage retained.

Dwa operator findings:

1. privileged supervisor wrapper odwołujący się do istniejącego Hermes user managera
   powinien używać `runuser` z `XDG_RUNTIME_DIR=/run/user/<uid>`. Nie zakładać, że
   samo `runuser ... systemctl --user` odziedziczy właściwy bus. Nie wymuszać
   `DBUS_SESSION_BUS_ADDRESS`, jeśli istniejący user manager działa przez
   `XDG_RUNTIME_DIR`; podczas tej walidacji jawny bus address powodował failure.
2. historyczny recovery release może nie zawierać validatora dodanego później.
   Dla D.0 r2 użyto zweryfikowanego historycznego validatora odpowiadającego D.0
   semantics zamiast zakładać jego obecność w starym release artifact.

Pełny evidence:
[production validation report](../../docs/reports/AI_PLATFORM_STAGE_D6_PRODUCTION_VALIDATION_2026-09-22_PL.md).

## Stage D closure — 2026-09-22

Production evidence zostało zapisane w repo. PR #47 został scalony do `main`
jako `62f00ab2a1aade2be9cc86d69e068647652d5a27`. Pre-merge AI Platform CI #451
oraz post-merge AI Platform CI #452 zakończyły się PASS; post-merge run obejmował
pełny test suite i `Validate Stage D release build`.

Live client cancellation pozostaje jawnie `NOT RUN`, z zachowanym automatycznym
coverage zgodnie z runbookiem. Nie blokuje to zamknięcia zatwierdzonego gate.

**Stage D = COMPLETE.**
