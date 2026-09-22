# Stage F: GPU runtime blocker

Status: **BLOCKED by local GPU execution failure**, not external participants.
Stage F remains a draft; Stage G/H have not started. No Stage F release was built
or installed in production, and the planned candidate/rollback/reactivation
acceptance cycle has not run. Stage E's completed migration history is unchanged.

The operator-approved SYNTHETIC/INTERNAL E2E boundary remains sufficient for F
acceptance once all changed internal boundaries and production compatibility pass.
External Telegram/Discord inbound transport remains **DEFERRED/NOT TESTED**.
D.6 external-user evidence is historical only. No failed probe is labeled PASS.

## Runtime finding and containment

Kernel journal entries show `amdgpu ... MES ring buffer is full.` beginning at
**2026-09-22 23:56:36 CEST**, before this resumed task. Errors continued through the
recovery attempt. Development chat probes could not finish real inference. The
first selected Bridge's base Qwen model rather than Hermes's configured 64k model;
the harness now reads the configured Hermes model and bounds output. This mismatch
does not explain away the pre-existing kernel fault.

Stopping the probes and asking Ollama to unload did not clear the stalled runner.
An independently reviewed, guarded emergency repair captured immutable private
Hermes recovery evidence, stopped the Gateway, restarted Ollama, and restarted the
same Stage E Gateway. The first attempt exposed a 60-second executor timeout shorter
than systemd's 90-second stop window; the retry used a bounded 180-second allowance.

HTTP readiness recovered, but **inference recovery did not**: the restarted model
service reported GPU discovery timeouts and `llm server not responding`, the
configured preload did not finish, `/api/ps` remained empty, and MES faults continued.
Endpoint readiness is not evidence of working inference. The emergency executor's
service-restored record explicitly leaves model inference pending; it is neither
Stage F acceptance nor the planned Stage F rollback test.

The guarded recovery path then paused inference ingress and recorded
`BASELINE_RUNTIME=BLOCKED_GPU_INGRESS_PAUSED`, returning failure rather than PASS:

- `/opt/ai-platform/current` still points to `stage-e-38fff86f7704`.
- AI Gateway is stopped. Hermes has MainPID 0 and an empty service cgroup; its known
  shutdown behavior leaves the unit label `failed` despite no surviving process.
- `ai-bridge-analysis.timer` is inactive.
- AI Bridge and telemetry/history remain active and unchanged.
- ComfyUI retains its original PID 28119 and an empty queue; it was not restarted.
- Hermes remains at pin `79445a496c86a19332ad786494b8384d2167e2d0` with the original
  three modified files/245 added lines. Config and source were not migrated.
- No model, domain data, D.0/D.6 evidence, or recovery point was deleted.

Private recovery archives, SQLite backups/integrity checks, source/config hashes,
and the boot-scoped GPU block marker are under `/var/lib/ai-platform/stage-f`.
The marker prevents another same-boot Stage F preflight from mistaking model-list
readiness for GPU recovery. Sanitized local incident evidence and executor logs are
under `/home/harrypotter/agent-state/manual-eh` (`f-gpu-blocker-evidence.json`,
`f-baseline-recovery*.log`, `f-gpu-safe-pause.log`). No credentials or conversation
contents are published here.

## Draft implementation and remaining work

[PR #63](https://github.com/autoklinika/AI-server/pull/63) remains **draft**, not merged.
It contains a supported-hook Hermes adapter, an internal harness, release/gate
scripts, recovery safeguards, and offline contract/failure tests. CI builds are
code/build evidence only; they do not substitute for production GPU execution.
The final local suite passed **773 tests**; internal production E2E is **NOT PASSED**.

Independent review rejected F cutover. Atomic replacement/staged plugin installation
and interruption-preserving recovery were added after that review. Remaining review
items must still be closed and independently re-reviewed on a frozen revision:

1. Track/reap detached harness media workers on every failure; preserve their state
   until admission and Comfy cleanup are verified.
2. Exercise the installed plugin through normal discovery and the real Hermes turn
   runner, including streaming/error cleanup and real `/foto` attachment editing.
   Manual registration plus direct middleware calls is not sufficient acceptance.
3. Teach the autonomous supervisor to distinguish a repairable validation outcome
   from unsafe runtime, preserving a healthy candidate instead of unconditional
   rollback. No candidate was deployed by the legacy supervisor in this attempt.
4. Complete build/install, real internal/media and compatibility validation, planned
   E rollback, reactivation, reports, final CI/merge and post-merge CI before G/H.

The GPU fault requires a host/GPU recovery window. A shared-GPU reset or reboot
would interrupt the preserved ComfyUI/runtime and exceeds the reviewed component
restart; it was not improvised through the deployment privilege bridge. After that
recovery, prove configured-model inference and admitted media execution, restore
paused ingress/timer activation from the private snapshot, close the review gaps,
and resume the sequential migration. No external human-participant prerequisite
needs to be reinstated.
