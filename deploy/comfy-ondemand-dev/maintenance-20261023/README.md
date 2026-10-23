# Real Radeon 890M ComfyUI on-demand test — operator DEV maintenance

STAGED AND DRY-RUN VERIFIED, NOT YET EXECUTED.
NO PRODUCTION CUTOVER. This is a bounded disruptive maintenance test:
the existing production ai-gateway.service and comfyui.service are
temporarily stopped and subsequently restored, with NO permanent unit changes.
Hermes and other Gateway clients may be unavailable during the test.

Runnable files on the host:
 /srv/ai-data/staging/comfy-ondemand-maintenance-dev-20261023/
Script sources in this repository are byte-identical archives.

## Preflight evidence

- Gateway / ComfyUI / Ollama active; RM IDLE, queue 0/0.
- ComfyUI queue empty, models unloaded, cleanup_pending false.
- RTX Gen3 x4, P8 and near-empty VRAM.
- AMD PCI identity 1002:150e.
- No stale DEV port 11657, service or blocked marker.
- flock prevents parallel operator runs.
- --run as nonroot refuses service actions (verified).

## How to run

Read-only test (already executed, PASS):

    bash /srv/ai-data/staging/comfy-ondemand-maintenance-dev-20261023/run-maintenance-dev.sh --check

One actual DEV GPU maintenance run (sudo required; NOT EXECUTED):

    sudo bash /srv/ai-data/staging/comfy-ondemand-maintenance-dev-20261023/run-maintenance-dev.sh --run

The --run script captures effective unit settings and arms an independent
one-shot systemd safety timer BEFORE stopping production services.
The watchdog rollback script is copied root-owned into /run. A normal
exit, failure or signal performs restoration immediately; if the operator
shell is killed, the independent timer attempts restoration.

Rollback stops only the fixed DEV ComfyUI unit, verifies its PID/cgroup
and the DEV port are absent, THEN starts original comfyui.service and
ai-gateway.service. It REFUSES to restart production when a GPU test
process remains alive, preferring a blocked maintenance state to
simultaneous unsafely sharing ROCm contexts.

The actual GPU script uses in-memory DEV Gateway / the existing single
RM PriorityScheduler, no new coordinator and no installed units.
It starts a fixed transient root-managed systemd unit, as user harrypotter,
with DevicePolicy=closed, AMD KFD/renderD128 allowlist, MemoryMax 9G,
Restart=no and RuntimeMaxSec 240s. It does NOT set unsupported GPU
visibility values (-1) and does NOT use --cpu.

The test attests service PID, process birth, boot-ID, InvocationID,
cgroup, AMD GPU name and GPU device handles. It attempts to decode
a small 64x64 image with existing Flux2 VAE, then checks RM queue,
unload, process stop and cleanup. An error leaves the DEV recovery marker.
The unit must be confirmed stopped before rollback starts production.

## Limits of this result

Even a PASS of a small real VAE image does not prove full ROCm/KFD driver
E_safe, global GPU access exclusivity or safe concurrency with every
other engine. A permanent on-demand production controller has not been
authorized or installed, and ai-gateway.service still requires
comfyui.service in its original configuration. That boot dependency
will need a separate staged transition and future operator approval.

Preserve NO-GO for GPU_REUSE_SAFE, SHARED/N1 grants and production cutover.

Logs (after executing --run): original unit snapshots in backup/,
real-gpu-dev.log, real-comfy-gpu-result.json, rollback.log and watchdog-setup.log.


## 2026-10-23: first operator run FAILED; original production RESTORED

The first real operator --run produced:

- MAINTENANCE_PREFLIGHT_PASS_RM_AND_PHYSICAL_GPU
- ROLLBACK_WATCHDOG_ARMED
- GPU_OWNER_FREE_WINDOW_PASS
- REAL_COMFY_DEV_FAIL_CLOSED RuntimeError
- PRODUCTION_RESTORE_PASS (MAINTENANCE_EXIT_CODE=19)

Systemd journal revealed the exact cause: ComfyUI user harrypotter
could not read its own --user-directory. The original harness ran under
sudo + umask 077 and created input/output/temp/user as root:root mode 0700,
inaccessible to the isolated nonroot ComfyUI unit.

The original production Gateway and ComfyUI were automatically restored.
The DEV process/watchdog no longer exist; the original negative result,
root-owned log and DEV recovery marker are preserved. Do not classify
this failed run as an AMD GPU or RM scheduler fault.

**Two-stage operator procedure (NOT executed by the assistant):**

1. sudo bash /srv/ai-data/staging/comfy-ondemand-maintenance-dev-20261023/recover-after-failure-dev.sh --repair

   This fixed, root-only audit verifies the precise current-boot
   systemd error, production health, GPU holders and saved fail-closed
   result. It changes only the four DEV input/output/temp/user directories
   to owner harrypotter:harrypotter mode 0700; tests real nonroot access;
   archives the negative evidence SHA256 and moves the *DEV-only* marker.
   No systemd stop/start or production permissions are changed.

2. bash /srv/ai-data/staging/comfy-ondemand-maintenance-dev-20261023/run-maintenance-dev.sh --check

   This is a read-only prerequisite. The test will REFUSE to stop
   production services unless all four DEV directories are correctly
   owned and writable by harrypotter.

Only after PASS and a separate operator decision, run the original
--run maintenance command. It temporarily interrupts Gateway/Hermes
and production ComfyUI and uses the same bounded rollback watchdog.

The AMD GPU driver-safe handoff, global process-device exclusivity and
real GPU on-demand acceptance remain NOT VERIFIED until the actual
new test passes. Preserve the operator-only fail-closed marker on
any further unresolved failure.

Full incident audit:
docs/reports/RM_COMFY_GPU_MAINTENANCE_FAILURE_AND_RECOVERY_2026-10-23_PL.md
