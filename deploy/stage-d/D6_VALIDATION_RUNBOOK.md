# D.6 production validation handoff

Status: **READY FOR PRODUCTION VALIDATION** — implementation ready for supervisor
validation. All live gates below are **NOT RUN** by the preparation agent.
Only the supervisor/operator can schedule and authorize the production window.
No command in this document grants permission to change production.

## Offline gate and release identity

Run the full `PYTHONPATH=src python -m pytest` suite. The focused regression set is:

```bash
PYTHONPATH=src python -m pytest tests/test_gateway_scheduler.py tests/test_gateway_priority_classes.py tests/test_gateway_jobs.py tests/test_gateway_resource_leases.py tests/test_gateway_unified_admission.py tests/test_compatibility_migration.py tests/test_media_admission.py tests/test_stage_d_foundation.py tests/test_stage_d6_preparation.py
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

Inventory must include the packaged ComfyUI adapter, repo resource helper,
installed copies of `hermes_resource_queue.py`, foto/video global dispatchers,
foto/video prompt compilers (including Stage30 base compiler), and both wrappers.
A release build does not install libexec copies. Resolve the actual installed
paths and compare them with candidate source **before** the window. Capture each
previous file and its destination/checksum as a matched rollback set. Any missing
mapping or backup blocks production validation; do not guess paths or extend the
Hermes patch. Existing product/model/GPU configuration must remain unchanged.

Install without activation and use `validate_installed_release.sh` only in the
later authorized window. It retains checksum, final-path, preflight and unchanged
runtime checks. Existing installation/cutover scripts require operator privileges;
the preparation agent must not execute them. Preserve all health/idle guards.
Activation must have a healthy Bridge/Gateway, no active analysis, Resource Manager
0/0/0 and empty ComfyUI queue. Use the existing guarded activation procedure;
never force a switch around a failed guard.

## WVC regression

After authorized candidate activation, run `validate_wvc_gateway_runtime.sh`.
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
Record service PIDs before/after and verify unchanged, active services.

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
idle queues afterward and unchanged Bridge/Gateway/Hermes/ComfyUI PIDs.
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

Use existing `rollback_release.sh <known-good-id>` for the explicit target;
no-argument rollback remains the immediate-previous emergency path. Preserve its
checksum/idle/health checks and failure trap restoring the source release.
Restore the matched helper/compiler/dispatcher set from the inventory alongside
release rollback; never run a mixed D.6 helper against historical admission APIs.
Do not remove the snapshots after reactivation.

At each side: verify symlink/RELEASE, expected metadata (historical D.0 is valid),
checksums, healthy Bridge/Gateway, Resource Manager 0/0/0, empty ComfyUI queues,
canonical units, expected timer state, media preflight, WVC and user-path smoke.
Use historical validators from the rollback release for D.0; current D.6 validators
intentionally reject D.0. Hermes/ComfyUI PIDs must remain unchanged across the cycle;
Bridge/Gateway restarts are expected only within the authorized switch procedure.
After reactivation rerun D.6 metadata/WVC/media/multiuser gates and verify the
previous-release record identifies the intended recovery target.

Record failure and recovery outcome separately if a switch fails. Never mark a
failed attempt PASS merely because the automatic source restore ran. Supervisor
owns final production evidence, CI/merge and any eventual COMPLETE designation.
