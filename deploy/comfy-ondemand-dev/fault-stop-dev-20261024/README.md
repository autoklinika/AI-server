# ComfyUI on-demand: one controlled real AMD GPU stop-failure test (DEV)

**STAGED / READ-ONLY PREFLIGHT PASS / REAL AMD FAULT NOT EXECUTED.**
**NO PRODUCTION CUTOVER. GPU_REUSE_SAFE=NOT_VERIFIED.**

This is the first intentionally faulted **real GPU** test after the
successful single 64x64 Flux2 VAE cycle. It tests a deliberately
refused process-stop acknowledgment AFTER a genuine VAE decode,
not a device hang, worker SIGKILL or GPU memory exhaustion.

The existing one-slot RM retains its media lease, and the DEV recovery
marker must remain when the controller refuses shutdown. Only the
operator's independent systemd rollback is allowed to stop the
particular DEV unit and subsequently restart the original production
ComfyUI and Gateway.

It must never be run at the same time as the existing live ComfyUI
holding AMD KFD/renderD128. The runner therefore requires a real
operator maintenance interruption.

Scripts are stored on the authorized host:

 /srv/ai-data/staging/comfy-ondemand-faults-dev-20261024/

Before testing (non-disruptive, performed and PASS):

    bash /srv/ai-data/staging/comfy-ondemand-faults-dev-20261024/run-fault-window-dev.sh --check

Operator-only test requiring sudo, NOT YET EXECUTED:

    sudo bash /srv/ai-data/staging/comfy-ondemand-faults-dev-20261024/run-fault-window-dev.sh --run

The --run script is derived from the operator-proven 23 October
maintenance procedure. It validates all production services, queues,
AMDGPU PCI identity, source workdir ownership and idle RTX, then arms
an independent root-owned timed rollback BEFORE stopping the old
Gateway and ComfyUI. A lock blocks parallel maintenance procedures.
It starts precisely one transient root-managed ComfyUI worker, tests
device/cgroup ownership, executes a small 64x64 Flux2 VAE image and
intentionally has the DEV process controller refuse to acknowledge
stop. The test verifies the resulting real RM failure result,
original media lease and persistent recovery marker.

The runner counts this precisely recognized injected failure as a
successful *negative test* **only if** the VAE PNG was produced and
the recovery fence is intact. It always invokes rollback before
finishing; the rollback stops and verifies the DEV process and port
before restarting original production ComfyUI and Gateway.

If the rollback cannot prove the DEV unit stopped, it does NOT
restart production beside an unknown AMD GPU owner. This may cause
an outage requiring the operator's manual recovery. An independent
watchdog timer backs up the rollback when the controlling shell dies.

**This does NOT prove:**
- abrupt external GPU worker termination during active kernels;
- AMD kernel driver safe reuse after SIGKILL/aborted GPU work;
- GPU OOM during a running ROCm kernel;
- simultaneous N1/SHARED AMD/RTX grants;
- safe production ComfyUI/Hermes cutover.

The test's full result must be read and reviewed after execution.
Any remaining DEV recovery marker must NOT be deleted without
a subsequent explicit, recorded DEV recovery process. Never
rerun --run before recovery and full baseline revalidation.

Do not install these scripts or units in production. They require
fresh operator authorization and may interrupt Hermes/Gateway.


## Operator execution result — 24 October 2026

The operator executed one controlled real AMD stop-refusal trial.
Actual output:

- DEV_COMFY_UID_DIRECTORY_RW_PASS
- MAINTENANCE_PREFLIGHT_PASS_RM_AND_PHYSICAL_GPU
- ROLLBACK_WATCHDOG_ARMED
- GPU_OWNER_FREE_WINDOW_PASS
- REAL_GPU_DEV_START
- DEV_EXPECTED_STOP_FAILURE_PENDING_ROLLBACK
- PRODUCTION_RESTORE_PASS
- MAINTENANCE_EXIT_CODE=0

Independently verified ComfyUI journal: AMD Radeon 890M (PyTorch ROCm),
Flux2 VAE decode on cuda:0, prompt completed in 0.66 s, resulting
PNG 64x64, 7922 bytes and sha256
16e0117ddd83e8d051956f3e70cfccf1e9ac81e091f19527383b13fe0d44f205.
Transient systemd process stopped successfully during rollback
(~5.1s wall, 1.3G RAM peak). Production ComfyUI/Gateway active,
RM IDLE, watchdog inactive, no DEV port, RTX P8 2MiB Gen3x4,
no GPU errors in checked kernel window.

The negative DEV RM result and recovery marker are retained
root-owned, as they MUST be after a simulated controller stop refusal.
They are not evidence of a real AMD driver crash or E_safe.

Detailed report:
docs/reports/RM_COMFY_STOP_REFUSAL_REAL_GPU_DEV_2026-10-24_PL.md
Independent JSON:
docs/reports/RM_COMFY_REAL_GPU_STOP_FAULT_DEV_2026-10-24.json

To review before accepting a recovery (READ-ONLY, already PASS):

    bash /srv/ai-data/staging/comfy-ondemand-faults-dev-20261024/review-and-archive-stop-fault-dev.sh --check

A separate root operator action can verify the original failure
record, expected trace, current production health and the sole
AMD GPU owner, archive root-only logs with SHA256 and then move
ONLY the DEV recovery marker:

    sudo bash /srv/ai-data/staging/comfy-ondemand-faults-dev-20261024/review-and-archive-stop-fault-dev.sh --archive

This --archive has NOT BEEN EXECUTED and DOES NOT touch production.
NEVER re-run the fault pilot while the marker exists. Even after
archival, GPU_REUSE_SAFE/E_safe remains NOT_VERIFIED. Future
GPU SIGKILL/OOM tests require a separately reviewed maintenance
window and must not be inferred from this injected stop-refusal pass.


## Archive status after operator action (24 October 2026)

The operator subsequently ran the separately scoped
review-and-archive-stop-fault-dev.sh --archive successfully:
- exact injected fault record PASS
- solely restored ComfyUI owns AMD GPU PASS
- SHA256 backup of negative logs PASS
- archived DEV marker removed from active staging PASS

A new independent read-only check confirmed the archive directory
exists with root:root 0700, active DEV marker/result absent, production
Gateway/ComfyUI/Ollama still active and RM IDLE 0/0 without recovery.
The archive interior could not be read from the nonroot account:
the original bytes/hash PASS is supported by the operator script output,
not by an independent nonroot full-file audit.

No further real GPU fault test was executed, no production on-demand
enablement took place, and GPU_REUSE_SAFE stays NOT_VERIFIED.

Machine evidence:
docs/reports/RM_COMFY_STOP_FAULT_ARCHIVE_ACCEPTED_2026-10-24.json
