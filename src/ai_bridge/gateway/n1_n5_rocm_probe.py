"""Hardware-grounded N1→N5 DENIAL probe. Does not execute GPU kernels.

Uses a real parked ROCm process and accurate process identity, the DEV Vision
provider registry, and N3's non-approving adapter. On this stage all requests
MUST be denied. This validates wiring, not a physical GPU grant or E_safe.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
import select
import subprocess
from time import time
from uuid import uuid4

from .accelerator_admission import (
    AcceleratorAdmission, AdmissionError, Claim, PoolPolicy, ProcessIdentity, Profile,
)
from .accelerator_evidence import NonApprovingSafetyAdapter
from .managed_worker_observer import WorkerObserver
from .n1_n5_cpu_bridge import CPUHandshake
from .rocm_maintenance_pilot import DEV_ROOT, check_readiness, PilotBlocked
from .rocm_test_worker import EXPECTED_PCI


class ParkedROCmRuntime(CPUHandshake):
    def activate(self, child):
        # No physical N1 grant is possible with the read-only N3 adapter.
        # Keep this runnable probe incapable of turning on HIP via GO.
        raise PilotBlocked("real GPU activation requires trusted E_safe")

    def spawn(self):
        path = Path(__file__).with_name("rocm_parked_worker.py")
        child = subprocess.Popen(
            ["/opt/comfyui/venv/bin/python", "-u", "-I", str(path)],
            start_new_session=True, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, close_fds=True,
        )
        try:
            if not select.select([child.stdout], [], [], 2.0)[0]:
                raise PilotBlocked("parked ROCm worker readiness timeout")
            if child.stdout.readline() != b"READY\n" or child.poll() is not None:
                raise PilotBlocked("parked ROCm worker failed to start")
            return child
        except BaseException:
            self.abort(child)
            raise


def make_n1(folder):
    from ai_bridge.providers.accelerators import (
        AcceleratorDescriptor, AcceleratorRegistry, ProviderAcceleratorBinding)
    from ai_bridge.providers.registry import (
        CapabilityDescriptor, DescriptorRegistry, LogicalProviderDescriptor, NodeDescriptor)
    provider_id = "vision-rocm-dev"
    providers = DescriptorRegistry(
        nodes=(NodeDescriptor(node_id="ai-node-01"),),
        capabilities=(CapabilityDescriptor(capability_id="gpu-job", provider_types=("agent",)),),
        providers=(LogicalProviderDescriptor(provider_id=provider_id,
            provider_type="agent", node_id="ai-node-01", capabilities=("gpu-job",)),))
    devices = AcceleratorRegistry(accelerators=(AcceleratorDescriptor(
        accelerator_id="radeon-890m-dev", node_id="ai-node-01",
        kind="integrated", backend="rocm", memory_class="unified",
        total_memory_bytes=1024**3, workload_classes=("vision",)),),
        provider_bindings=(ProviderAcceleratorBinding(
            provider_id=provider_id, accelerator_ids=("radeon-890m-dev",)),))
    adapter = NonApprovingSafetyAdapter("rocm")
    policy = PoolPolicy(accelerator_id="radeon-890m-dev",
        adapter_id=adapter.adapter_id, memory_limit_bytes=1024**3,
        profiles=(Profile(profile_id="vision-test-dev", provider_id=provider_id,
            workload_class="vision", reserved_bytes=4096),))
    return AcceleratorAdmission(devices, providers, (policy,), (adapter,),
                                folder / "n1-journal.jsonl", enabled=True)


async def run_denial_probe(folder: Path, *, preflight=check_readiness):
    if folder.exists():
        raise PilotBlocked("probe attempt path already exists")
    preflight()
    folder.mkdir(parents=True, mode=0o700)
    marker = folder / "n5-ownership.dirty"
    rm = None
    observer = WorkerObserver(marker, runtime=ParkedROCmRuntime(),
                              marker_label="HARDWARE-PILOT")
    child = None
    result = {"schema": 1, "n1": "BLOCKED", "n5": "NOT_STARTED",
              "gpu_execution": "DENIED", "gpu_reuse_safe": "NOT_VERIFIED",
              "pci_bdf": EXPECTED_PCI, "timestamp": time()}
    try:
        rm = make_n1(folder)
        identity = observer.start()
        child = observer._child
        result.update({"n5": "PARKED_BEFORE_GPU", "pid": identity.pid,
                       "boot_id": identity.boot_id})
        try:
            await rm.recover("radeon-890m-dev")
        except AdmissionError:
            result["recovery"] = "DENIED_BY_N3"
        else:
            raise RuntimeError("unsafe approval of unverified GPU recovery")
        claim = Claim(request_id="vision-dev-" + uuid4().hex,
                      accelerator_id="radeon-890m-dev", provider_id="vision-rocm-dev",
                      profile_id="vision-test-dev", mode="EXCLUSIVE",
                      process=ProcessIdentity(boot_id=identity.boot_id, pid=identity.pid,
                          birth_ticks=identity.birth_ticks, scope=identity.scope))
        rm.submit(claim)
        try:
            await rm.wait(claim.request_id, timeout=0.2)
        except asyncio.TimeoutError:
            result["grant"] = "DENIED"
        else:
            raise RuntimeError("unsafe N1 grant issued without trusted E_safe")
        state = rm.snapshot()["radeon-890m-dev"]
        if not state["blocked"] or state["active"]:
            raise RuntimeError("N1 denial was not fail-closed")
        if child.poll() is not None:
            raise RuntimeError("parked worker died unexpectedly")
        result["n1"] = "BLOCKED_EXPECTED"
    finally:
        observer.cancel()
        ParkedROCmRuntime.abort(child or observer._child)
        if rm:
            rm.close()
        result["postflight"] = preflight()
        (folder / "gate-result.json").write_text(json.dumps(result, indent=2, sort_keys=True))
    return result


def main():
    import sys
    if len(sys.argv) != 1:
        raise SystemExit("no arguments accepted")
    folder = DEV_ROOT / ("n1-n5-gate-" + uuid4().hex[:12])
    print(json.dumps(asyncio.run(run_denial_probe(folder)), sort_keys=True))


if __name__ == "__main__":
    main()
