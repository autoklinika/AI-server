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
