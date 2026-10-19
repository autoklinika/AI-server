"""N1/N5 two-phase integration tests. Real process is stdlib CPU only."""
import asyncio

import pytest

from ai_bridge.gateway.accelerator_admission import (
    AcceleratorAdmission, AdmissionError, PoolPolicy, Profile,
)
from ai_bridge.gateway.accelerator_evidence import NonApprovingSafetyAdapter
from ai_bridge.gateway.n1_n5_cpu_bridge import N1N5CPUBridge
from ai_bridge.providers.accelerators import (
    AcceleratorDescriptor, AcceleratorRegistry, ProviderAcceleratorBinding,
)
from ai_bridge.providers.registry import local_descriptor_registry


@pytest.fixture
def anyio_backend():
    return "asyncio"


class CPUTestAdapter:
    adapter_id = "cpu-contract-only"
    backend = "cpu"
    def __init__(self, *, allow=True):
        self.allow = allow
        self.verified = []
    def can_start(self, device, claim, active):
        return self.allow
    async def verify(self, challenge):
        self.verified.append(challenge)
        return self.allow


def make_core(tmp_path, *, gpu=False, adapter=None):
    descriptor = AcceleratorDescriptor(
        accelerator_id="local-test", node_id="ai-node-01",
        kind="integrated" if gpu else "virtual",
        backend="rocm" if gpu else "cpu",
        memory_class="unified" if gpu else "host",
        total_memory_bytes=1024**3,
        workload_classes=("llm",))
    registry = AcceleratorRegistry(accelerators=(descriptor,),
        provider_bindings=(ProviderAcceleratorBinding(
            provider_id="ollama-local", accelerator_ids=("local-test",)),))
    adapter = adapter or (NonApprovingSafetyAdapter("rocm")
                          if gpu else CPUTestAdapter())
    policy = PoolPolicy(accelerator_id="local-test", adapter_id=adapter.adapter_id,
        memory_limit_bytes=1024**3, profiles=(
            Profile(profile_id="cpu-test", provider_id="ollama-local",
                    workload_class="llm", reserved_bytes=4096),))
    rm = AcceleratorAdmission(registry, local_descriptor_registry(), (policy,),
                              (adapter,), tmp_path / "n1-journal", enabled=True)
    return rm, adapter


@pytest.mark.anyio
async def test_cpu_real_child_only_after_n1_grant(tmp_path):
    rm, adapter = make_core(tmp_path)
    await rm.recover("local-test")
    bridge = N1N5CPUBridge(rm, accelerator_id="local-test",
                           provider_id="ollama-local", profile_id="cpu-test",
                           marker=tmp_path / "n5-attempt")
    result = await bridge.run()
    assert result["n1"] == "RELEASED_CPU_ONLY"
    assert result["cpu_worker"] == "PROCESS_CLOSED"
    assert result["gpu_reuse_safe"] == "NOT_VERIFIED"
    assert not rm.snapshot()["local-test"]["active"]
    assert len(adapter.verified) == 2
    assert (tmp_path / "n5-attempt").exists()
    with pytest.raises(RuntimeError, match="DIRTY"):
        await bridge.run()
    rm.close()


@pytest.mark.anyio
async def test_cpu_grant_denied_keeps_marker_and_no_start(tmp_path):
    rm, adapter = make_core(tmp_path, adapter=CPUTestAdapter(allow=False))
    bridge = N1N5CPUBridge(rm, accelerator_id="local-test",
                           provider_id="ollama-local", profile_id="cpu-test",
                           marker=tmp_path / "attempt")
    with pytest.raises(asyncio.TimeoutError):
        await bridge.run(timeout=0.2)
    assert rm.snapshot()["local-test"]["blocked"]
    assert not rm.snapshot()["local-test"]["active"]
    assert (tmp_path / "attempt").exists()
    rm.close()


@pytest.mark.anyio
async def test_cpu_release_denied_keeps_claim_pinned(tmp_path):
    adapter = CPUTestAdapter()
    rm, adapter = make_core(tmp_path, adapter=adapter)
    await rm.recover("local-test")
    # The adapter grants the claim but later fails its independent release.
    async def verify(challenge):
        return False
    adapter.verify = verify
    bridge = N1N5CPUBridge(rm, accelerator_id="local-test",
                           provider_id="ollama-local", profile_id="cpu-test",
                           marker=tmp_path / "attempt")
    with pytest.raises(AdmissionError):
        await bridge.run()
    state = rm.snapshot()["local-test"]
    assert state["blocked"]
    assert len(state["active"]) == 1
    assert (tmp_path / "attempt").exists()
    rm.close()


@pytest.mark.anyio
async def test_real_rocm_policy_never_grants_and_never_launches(tmp_path):
    rm, _ = make_core(tmp_path, gpu=True)
    with pytest.raises(RuntimeError, match="NOT_ADMITTED"):
        N1N5CPUBridge(rm, accelerator_id="local-test",
                      provider_id="ollama-local", profile_id="cpu-test",
                      marker=tmp_path / "attempt")
    with pytest.raises(AdmissionError, match="cleanup evidence"):
        await rm.recover("local-test")
    assert rm.snapshot()["local-test"]["blocked"]
    assert not (tmp_path / "attempt").exists()
    rm.close()
