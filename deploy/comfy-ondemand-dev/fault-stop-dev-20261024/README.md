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
