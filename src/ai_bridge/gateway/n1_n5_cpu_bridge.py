"""DEV N1→N5 two-phase CPU integration; NEVER grants physical GPU access.

The worker is created parked (no GPU imports or device calls). N1 receives its
actual PID / boot / birth identity, and may approve it using only a CPU synthetic
test SafetyAdapter. GPU/ROCm descriptors are rejected regardless of adapter.
This proves sequencing and failure handling, not physical GPU E_safe.
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path
import select
import subprocess
import sys
from uuid import uuid4

from .accelerator_admission import AcceleratorAdmission, Claim, ProcessIdentity
from .managed_worker_observer import SyntheticCPU, WorkerObserver


_PARKED_CPU = (
    "import sys; "
    "sys.stdout.buffer.write(b'READY\\n'); sys.stdout.buffer.flush(); "
    "signal=sys.stdin.buffer.read(1); "
    "sys.exit(2) if signal!=b'G' else None; "
    "sum(i*i for i in range(10000)); "
    "sys.stdout.buffer.write(b'DONE\\n'); sys.stdout.buffer.flush()"
)


class CPUHandshake(SyntheticCPU):
    """Private fixed stdlib-only executable. Parent controls its single gate."""
    def spawn(self):
        child = subprocess.Popen(
            [sys.executable, "-u", "-I", "-S", "-c", _PARKED_CPU],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            close_fds=True, start_new_session=True,
        )
        try:
            if not select.select([child.stdout], [], [], 2.0)[0]:
                raise RuntimeError("parked worker readiness timeout")
            if child.stdout.readline() != b"READY\n" or child.poll() is not None:
                raise RuntimeError("parked worker startup failed")
            return child
        except BaseException:
            self.abort(child)
            raise

    def activate(self, child):
        if child.poll() is not None:
            raise RuntimeError("parked worker exited before admission")
        child.stdin.write(b"G")
        child.stdin.flush()
        child.stdin.close()

    @staticmethod
    def abort(child):
        if child is not None and child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=3)
            except subprocess.TimeoutExpired:
                # Remain DIRTY. Do not send process-group signals.
                raise RuntimeError("CPU child still alive after termination request")

    @staticmethod
    def result(child):
        return child.stdout.read() == b"DONE\n"


class N1N5CPUBridge:
    """Integrates N1 and N5 for CPU proof only, fail-closed on any exception."""
    def __init__(self, rm: AcceleratorAdmission, *, accelerator_id: str,
                 provider_id: str, profile_id: str, marker: Path):
        device = rm._registry.accelerator(accelerator_id)
        if device.backend != "cpu" or device.kind != "virtual":
            raise RuntimeError("real GPU N1/N5 bridge is NOT_ADMITTED")
        self.rm, self.device = rm, accelerator_id
        self.provider, self.profile = provider_id, profile_id
        self.marker = marker

    async def run(self, *, timeout: float = 3.0, runtime=None):
        if self.marker.exists():
            raise RuntimeError("prior CPU attempt marker: DIRTY")
        if type(timeout) not in (float, int) or not 0 < timeout <= 10:
            raise ValueError("invalid bounded CPU timeout")
        runtime = runtime or CPUHandshake()
        observer = WorkerObserver(self.marker, runtime=runtime)
        request = None
        grant = None
        child = None
        try:
            # Prepare does no GPU work. It makes the real PID known to N1.
            identity = observer.start()
            child = observer._child
            request = "cpu-proof-" + uuid4().hex
            claim = Claim(request_id=request, accelerator_id=self.device,
                          provider_id=self.provider, profile_id=self.profile,
                          mode="EXCLUSIVE", process=ProcessIdentity(
                              boot_id=identity.boot_id, pid=identity.pid,
                              birth_ticks=identity.birth_ticks, scope=identity.scope))
            self.rm.submit(claim)
            grant = await self.rm.wait(request, timeout=timeout)
            if grant.claim != claim or self.rm.snapshot()[self.device]["blocked"]:
                raise RuntimeError("invalid or blocked N1 grant")
            runtime.activate(child)
            outcome = await asyncio.to_thread(observer.observe, timeout=timeout)
            if outcome != "PROCESS_CLOSED" or not runtime.result(child):
                raise RuntimeError("CPU worker failed or unverifiable")
            await self.rm.release(grant)
            # This proves the synthetic CPU test only; durable attempt retained.
            return {"cpu_worker": "PROCESS_CLOSED", "n1": "RELEASED_CPU_ONLY",
                    "gpu_reuse_safe": "NOT_VERIFIED",
                    "pid": identity.pid, "request_id": request}
        except BaseException:
            if request is not None:
                try:
                    self.rm.cancel(request)
                except (KeyError, RuntimeError):
                    pass
            observer.cancel()
            raise
        finally:
            if child is None:
                child = getattr(observer, "_child", None)
            runtime.abort(child)
