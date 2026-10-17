"""CPU-only synthetic contracts: no real adapter, process probe or GPU I/O."""
import asyncio
from dataclasses import replace

import pytest

from ai_bridge.gateway.accelerator_admission import (
    AcceleratorAdmission, AdmissionError, Claim, PoolPolicy, ProcessIdentity, Profile,
)
from ai_bridge.providers.accelerators import (
    AcceleratorDescriptor, AcceleratorRegistry, AcceleratorRequirements, ProviderAcceleratorBinding,
)
from ai_bridge.providers.registry import local_descriptor_registry


@pytest.fixture
def anyio_backend():
    return "asyncio"


class SyntheticAdapter:
    adapter_id = "synthetic"
    backend = "cpu"

    def __init__(self):
        self.start = True
        self.safe = True
        self.entered = asyncio.Event()
        self.gate = None
        self.challenges = []

    def can_start(self, device, claim, active):
        if isinstance(self.start, Exception):
            raise self.start
        return self.start

    async def verify(self, challenge):
        self.challenges.append(challenge)
        self.entered.set()
        if self.gate:
            await self.gate.wait()
        if isinstance(self.safe, Exception):
            raise self.safe
        return self.safe


def configuration(devices=1, *, capacity=100, budget=40, sharing=True, maximum=2):
    registry = AcceleratorRegistry(
        accelerators=tuple(AcceleratorDescriptor(
            accelerator_id=f"gpu-{i}", node_id="ai-node-01", kind="virtual", backend="cpu",
            memory_class="host", total_memory_bytes=capacity, workload_classes=("llm",),
        ) for i in range(devices)),
        provider_bindings=(ProviderAcceleratorBinding(
            provider_id="ollama-local", accelerator_ids=tuple(f"gpu-{i}" for i in range(devices))),),
    )
    policies = tuple(PoolPolicy(
        accelerator_id=f"gpu-{i}", adapter_id="synthetic", memory_limit_bytes=capacity,
        profiles=(Profile(profile_id="p", provider_id="ollama-local", workload_class="llm", reserved_bytes=budget),),
        sharing_enabled=sharing, max_shared=maximum,
        compatible_pairs=(("p", "p"),), compatibility_report="synthetic-test-only",
    ) for i in range(devices))
    return registry, policies


def claim(name, *, device=0, mode="SHARED", priority=10, **changes):
    values = dict(request_id=name, accelerator_id=f"gpu-{device}", provider_id="ollama-local",
                  profile_id="p", mode=mode, priority=priority,
                  process=ProcessIdentity(boot_id="synthetic-boot", pid=100 + sum(map(ord, name)),
                                          birth_ticks=1, scope=f"scope-{name}"))
    values.update(changes)
    return Claim(**values)


def core(tmp_path, adapter, *, config=None, **kwargs):
    registry, policies = config or configuration()
    return AcceleratorAdmission(registry, local_descriptor_registry(), policies, (adapter,),
                                tmp_path / "ownership.jsonl", enabled=True, **kwargs)


@pytest.mark.anyio
async def test_shared_two_exclusive_barrier_and_fifo(tmp_path):
    rm = core(tmp_path, SyntheticAdapter())
    await rm.recover("gpu-0")
    for name in ("a", "b"):
        rm.submit(claim(name))
    a, b = await rm.wait("a"), await rm.wait("b")
    rm.submit(claim("x", mode="EXCLUSIVE"))
    rm.submit(claim("c"))
    assert len(rm.snapshot()["gpu-0"]["active"]) == 2
    await rm.release(a)
    assert rm.snapshot()["gpu-0"]["queued"] == ("x", "c")
    await rm.release(b)
    x = await rm.wait("x")
    assert rm.snapshot()["gpu-0"]["queued"] == ("c",)
    await rm.release(x)
    await rm.release(await rm.wait("c"))
    rm.close()


@pytest.mark.anyio
async def test_two_devices_independent_and_unique_resources(tmp_path):
    rm = core(tmp_path, SyntheticAdapter(), config=configuration(2))
    await rm.recover("gpu-0")
    await rm.recover("gpu-1")
    rm.submit(claim("a", mode="EXCLUSIVE"))
    rm.submit(claim("b", mode="EXCLUSIVE"))
    rm.submit(claim("c", device=1, mode="EXCLUSIVE"))
    a, c = await asyncio.gather(rm.wait("a"), rm.wait("c"))
    assert a.resource_id != c.resource_id
    assert rm.snapshot()["gpu-0"]["queued"] == ("b",)
    rm.close()


@pytest.mark.anyio
@pytest.mark.parametrize("capacity,budget,maximum,expected", [(100, 60, 2, 1), (120, 40, 3, 3), (100, 40, 3, 2)])
async def test_explicit_memory_and_slot_budgets(tmp_path, capacity, budget, maximum, expected):
    rm = core(tmp_path, SyntheticAdapter(), config=configuration(capacity=capacity, budget=budget, maximum=maximum))
    await rm.recover("gpu-0")
    for name in ("a", "b", "c", "d"):
        rm.submit(claim(name))
    assert len(rm.snapshot()["gpu-0"]["active"]) == expected
    rm.close()


@pytest.mark.anyio
async def test_priority_fifo_and_cancel_queue(tmp_path):
    rm = core(tmp_path, SyntheticAdapter())
    for name, priority in (("low", 20), ("first", 1), ("second", 1), ("cancel", 0)):
        rm.submit(claim(name, priority=priority, mode="EXCLUSIVE"))
    rm.cancel("cancel")
    await rm.recover("gpu-0")
    first = await rm.wait("first")
    assert first.claim.request_id == "first"
    await rm.release(first)
    await rm.release(await rm.wait("second"))
    await rm.release(await rm.wait("low"))
    rm.close()


@pytest.mark.anyio
@pytest.mark.parametrize("outcome", [False, None, 1, RuntimeError("verify failure")])
async def test_release_failure_pins_owner_and_requires_recovery(tmp_path, outcome):
    adapter = SyntheticAdapter()
    rm = core(tmp_path, adapter)
    await rm.recover("gpu-0")
    rm.submit(claim("a"))
    a = await rm.wait("a")
    adapter.safe = outcome
    with pytest.raises((AdmissionError, RuntimeError)):
        await rm.release(a)
    rm.submit(claim("b"))
    state = rm.snapshot()["gpu-0"]
    assert state["blocked"] and state["active"] == (a,) and state["queued"] == ("b",)
    with pytest.raises(AdmissionError):
        await rm.recover("gpu-0")
    adapter.safe = True
    await rm.release(a)
    assert rm.snapshot()["gpu-0"]["blocked"]
    await rm.recover("gpu-0")
    assert len(rm.snapshot()["gpu-0"]["active"]) == 1
    rm.close()


@pytest.mark.anyio
@pytest.mark.parametrize("outcome", [False, None, 1, RuntimeError("identity unknown")])
async def test_unknown_identity_blocks_admission(tmp_path, outcome):
    adapter = SyntheticAdapter()
    rm = core(tmp_path, adapter)
    await rm.recover("gpu-0")
    adapter.start = outcome
    rm.submit(claim("a"))
    assert rm.snapshot()["gpu-0"]["blocked"]
    assert not rm.snapshot()["gpu-0"]["active"]
    rm.close()


@pytest.mark.anyio
async def test_generation_aba_and_forgery(tmp_path):
    rm = core(tmp_path, SyntheticAdapter())
    await rm.recover("gpu-0")
    rm.submit(claim("a"))
    a = await rm.wait("a")
    await rm.release(a)
    rm.submit(claim("b"))
    b = await rm.wait("b")
    assert b.generation > a.generation
    for forged in (a, replace(b, generation=a.generation), replace(b, epoch="old"), replace(b, lease_id="other")):
        with pytest.raises(AdmissionError):
            await rm.release(forged)
    assert rm.snapshot()["gpu-0"]["active"] == (b,)
    rm.close()


@pytest.mark.anyio
async def test_restart_journal_dirty_and_explicit_recovery(tmp_path):
    adapter = SyntheticAdapter()
    rm = core(tmp_path, adapter)
    assert rm.snapshot()["gpu-0"]["blocked"]
    await rm.recover("gpu-0")
    rm.submit(claim("a"))
    old = await rm.wait("a")
    rm.close()  # Simulated crash: no release or cleanup.
    journal = (tmp_path / "ownership.jsonl").read_text()
    assert old.lease_id in journal and "birth_ticks" in journal
    rm = core(tmp_path, adapter)
    rm.submit(claim("b"))
    assert rm.snapshot()["gpu-0"]["blocked"]
    adapter.safe = False
    with pytest.raises(AdmissionError):
        await rm.recover("gpu-0")
    adapter.safe = True
    await rm.recover("gpu-0")
    new = await rm.wait("b")
    assert old.epoch != new.epoch
    with pytest.raises(AdmissionError):
        await rm.release(old)
    rm.close()


@pytest.mark.anyio
@pytest.mark.parametrize("granted", [False, True])
async def test_timeout_and_cancellation_preserve_granted_ownership(tmp_path, granted):
    rm = core(tmp_path, SyntheticAdapter())
    if granted:
        await rm.recover("gpu-0")
    rm.submit(claim("a"))
    if granted:
        rm.cancel("a")  # Includes partial startup / worker crash.
        assert rm.snapshot()["gpu-0"]["blocked"]
        assert len(rm.snapshot()["gpu-0"]["active"]) == 1
    else:
        with pytest.raises(TimeoutError):
            await rm.wait("a", timeout=0)
        assert not rm.snapshot()["gpu-0"]["queued"]
    rm.close()


@pytest.mark.anyio
async def test_cancellation_in_grant_delivery_window(tmp_path):
    rm = core(tmp_path, SyntheticAdapter())
    rm.submit(claim("a"))
    waiter = asyncio.create_task(rm.wait("a"))
    await asyncio.sleep(0)
    await rm.recover("gpu-0")
    waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter
    assert rm.snapshot()["gpu-0"]["blocked"]
    assert len(rm.snapshot()["gpu-0"]["active"]) == 1
    rm.close()


@pytest.mark.anyio
@pytest.mark.parametrize("cancel_verifier", [False, True])
async def test_release_cancel_race_fails_closed(tmp_path, cancel_verifier):
    adapter = SyntheticAdapter()
    rm = core(tmp_path, adapter)
    await rm.recover("gpu-0")
    rm.submit(claim("a"))
    a = await rm.wait("a")
    adapter.gate = asyncio.Event()
    adapter.entered.clear()
    task = asyncio.create_task(rm.release(a))
    await adapter.entered.wait()
    with pytest.raises(AdmissionError):
        await rm.release(a)
    if cancel_verifier:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    else:
        rm.cancel("a")
        adapter.gate.set()
        with pytest.raises(AdmissionError):
            await task
    assert rm.snapshot()["gpu-0"]["active"] == (a,)
    assert rm.snapshot()["gpu-0"]["blocked"]
    rm.close()


@pytest.mark.anyio
async def test_journal_write_failure_pins_and_blocks(tmp_path, monkeypatch):
    rm = core(tmp_path, SyntheticAdapter())
    await rm.recover("gpu-0")
    def fail(fd):
        raise OSError("disk unavailable")
    monkeypatch.setattr("ai_bridge.gateway.accelerator_admission.os.fsync", fail)
    with pytest.raises(OSError):
        rm.submit(claim("a"))
    assert rm.snapshot()["gpu-0"]["blocked"]
    assert len(rm.snapshot()["gpu-0"]["active"]) == 1
    rm.close()


@pytest.mark.anyio
async def test_one_instance_per_journal(tmp_path):
    rm = core(tmp_path, SyntheticAdapter())
    with pytest.raises(BlockingIOError):
        core(tmp_path, SyntheticAdapter())
    rm.close()


@pytest.mark.anyio
async def test_duplicates_and_bounded_state(tmp_path):
    rm = core(tmp_path, SyntheticAdapter(), max_requests=2, max_queue=1)
    rm.submit(claim("a"))
    with pytest.raises(AdmissionError):
        rm.submit(claim("a"))
    with pytest.raises(AdmissionError):
        rm.submit(claim("b"))
    rm.cancel("a")
    rm.submit(claim("b"))
    rm.cancel("b")
    with pytest.raises(AdmissionError):
        rm.submit(claim("c"))
    rm.close()


@pytest.mark.anyio
@pytest.mark.parametrize("changes", [
    {"provider_id": "comfyui-local"}, {"accelerator_id": "future"},
    {"profile_id": "unknown"}, {"requirements": AcceleratorRequirements(backends=("cuda",))},
    {"requirements": AcceleratorRequirements(min_memory_bytes=101)},
])
async def test_bad_claim_binding(tmp_path, changes):
    rm = core(tmp_path, SyntheticAdapter())
    with pytest.raises(AdmissionError):
        rm.submit(claim("a", **changes))
    assert not rm.snapshot()["gpu-0"]["active"]
    rm.close()


@pytest.mark.parametrize("changes", [
    {"mode": "other"}, {"priority": True}, {"priority": -1}, {"process": None},
    {"process": {"pid": 5}}, {"request_id": ""}, {"unexpected": 1},
])
def test_malformed_claim(changes):
    with pytest.raises(ValueError):
        claim("a", **changes)


@pytest.mark.anyio
@pytest.mark.parametrize("mutation", ["unknown-memory", "unknown-backend", "disabled", "wrong-adapter", "over-budget", "no-report", "no-pairs", "bad-pair", "bad-provider"])
async def test_invalid_configuration(tmp_path, mutation):
    registry, policies = configuration()
    device, policy = registry.accelerators[0], policies[0]
    if mutation == "unknown-memory":
        device = device.model_copy(update={"total_memory_bytes": None})
    elif mutation == "unknown-backend":
        device = device.model_copy(update={"backend": "unknown"})
    elif mutation == "disabled":
        device = device.model_copy(update={"enabled": False})
    elif mutation == "wrong-adapter":
        policy = policy.model_copy(update={"adapter_id": "not-installed"})
    elif mutation == "over-budget":
        policy = policy.model_copy(update={"memory_limit_bytes": 101})
    elif mutation == "no-report":
        policy = policy.model_copy(update={"compatibility_report": ""})
    elif mutation == "no-pairs":
        policy = policy.model_copy(update={"compatible_pairs": ()})
    elif mutation == "bad-pair":
        policy = policy.model_copy(update={"compatible_pairs": (("p", "unknown"),)})
    elif mutation == "bad-provider":
        policy = policy.model_copy(update={"profiles": (policy.profiles[0].model_copy(update={"provider_id": "comfyui-local"}),)})
    registry = registry.model_copy(update={"accelerators": (device,)})
    with pytest.raises(ValueError):
        core(tmp_path, SyntheticAdapter(), config=(registry, (policy,)))


@pytest.mark.anyio
async def test_disabled_by_default_and_sharing_opt_in(tmp_path):
    registry, policies = configuration(sharing=False)
    with pytest.raises(AdmissionError):
        AcceleratorAdmission(registry, local_descriptor_registry(), policies, (), tmp_path / "journal")
    rm = core(tmp_path, SyntheticAdapter(), config=(registry, policies))
    await rm.recover("gpu-0")
    with pytest.raises(AdmissionError):
        rm.submit(claim("a"))
    rm.submit(claim("b", mode="EXCLUSIVE"))
    assert (await rm.wait("b")).claim.mode == "EXCLUSIVE"
    rm.close()


@pytest.mark.anyio
async def test_pairwise_profiles_and_provider_budgets(tmp_path):
    registry, (policy,) = configuration()
    second = policy.profiles[0].model_copy(update={"profile_id": "q", "reserved_bytes": 50})
    policy = policy.model_copy(update={"profiles": (*policy.profiles, second),
                                       "compatible_pairs": (("p", "p"), ("q", "q"))})
    rm = core(tmp_path, SyntheticAdapter(), config=(registry, (policy,)))
    await rm.recover("gpu-0")
    rm.submit(claim("a"))
    rm.submit(claim("b", profile_id="q"))
    assert rm.snapshot()["gpu-0"]["queued"] == ("b",)
    await rm.release(await rm.wait("a"))
    b = await rm.wait("b")
    assert b.reserved_bytes == 50
    rm.close()


@pytest.mark.anyio
async def test_duplicate_worker_identity_and_revalidated_model(tmp_path):
    rm = core(tmp_path, SyntheticAdapter())
    a = claim("a")
    rm.submit(a)
    with pytest.raises(AdmissionError):
        rm.submit(claim("b", process=a.process))
    with pytest.raises(ValueError):
        rm.submit(a.model_copy(update={"priority": True, "request_id": "bad"}))
    rm.close()


@pytest.mark.anyio
async def test_release_persistence_failure_retains_identity(tmp_path, monkeypatch):
    rm = core(tmp_path, SyntheticAdapter())
    await rm.recover("gpu-0")
    rm.submit(claim("a"))
    a = await rm.wait("a")
    def fail(fd):
        raise OSError("release journal failure")
    monkeypatch.setattr("ai_bridge.gateway.accelerator_admission.os.fsync", fail)
    with pytest.raises(OSError):
        await rm.release(a)
    assert rm.snapshot()["gpu-0"]["active"] == (a,)
    assert rm.snapshot()["gpu-0"]["blocked"]
    rm.close()


@pytest.mark.anyio
async def test_verifier_receives_exact_identity_and_remaining_owners(tmp_path):
    adapter = SyntheticAdapter()
    rm = core(tmp_path, adapter)
    await rm.recover("gpu-0")
    rm.submit(claim("a"))
    rm.submit(claim("b"))
    a, b = await rm.wait("a"), await rm.wait("b")
    await rm.release(a)
    proof = adapter.challenges[-1]
    assert proof.grant == a and proof.remaining == (b,)
    assert a.lease_id.encode() in proof.journal
    assert b.lease_id.encode() in proof.journal
    assert proof.nonce != adapter.challenges[0].nonce
    rm.close()


@pytest.mark.anyio
async def test_concurrent_submit_capacity_and_cancelled_queue_waiter(tmp_path):
    rm = core(tmp_path, SyntheticAdapter())
    async def submit(i):
        rm.submit(claim(f"request-{i}"))
    await asyncio.gather(*(submit(i) for i in range(20)))
    waiter = asyncio.create_task(rm.wait("request-0"))
    await asyncio.sleep(0)
    waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter
    await rm.recover("gpu-0")
    state = rm.snapshot()["gpu-0"]
    assert len(state["active"]) == 2 and len(state["queued"]) == 17
    assert [g.claim.request_id for g in state["active"]] == ["request-1", "request-2"]
    rm.close()


@pytest.mark.anyio
async def test_unknown_pool_does_not_block_other_device(tmp_path):
    rm = core(tmp_path, SyntheticAdapter(), config=configuration(2))
    rm.submit(claim("blocked"))
    await rm.recover("gpu-1")
    rm.submit(claim("other", device=1))
    assert (await rm.wait("other")).claim.accelerator_id == "gpu-1"
    assert rm.snapshot()["gpu-0"]["blocked"]
    rm.close()


@pytest.mark.anyio
async def test_later_high_priority_shared_cannot_starve_waiting_exclusive(tmp_path):
    rm = core(tmp_path, SyntheticAdapter())
    await rm.recover("gpu-0")
    rm.submit(claim("active"))
    rm.submit(claim("exclusive", priority=100, mode="EXCLUSIVE"))
    rm.submit(claim("later", priority=0))
    assert len(rm.snapshot()["gpu-0"]["active"]) == 1
    await rm.release(await rm.wait("active"))
    exclusive = await rm.wait("exclusive")
    assert rm.snapshot()["gpu-0"]["queued"] == ("later",)
    await rm.release(exclusive)
    await rm.release(await rm.wait("later"))
    rm.close()


@pytest.mark.anyio
@pytest.mark.parametrize("timeout", [True, -1, float("inf"), float("nan"), "1"])
async def test_malformed_timeout_does_not_mutate_owner(tmp_path, timeout):
    rm = core(tmp_path, SyntheticAdapter())
    rm.submit(claim("a"))
    with pytest.raises(ValueError):
        await rm.wait("a", timeout=timeout)
    assert rm.snapshot()["gpu-0"]["queued"] == ("a",)
    rm.close()


@pytest.mark.anyio
async def test_verifier_deadline_pins_owner_without_external_timeout(tmp_path):
    adapter = SyntheticAdapter()
    rm = core(tmp_path, adapter, verification_timeout=0.02)
    await rm.recover("gpu-0")
    rm.submit(claim("a"))
    grant = await rm.wait("a")
    adapter.gate = asyncio.Event()
    with pytest.raises(TimeoutError):
        await rm.release(grant)
    state = rm.snapshot()["gpu-0"]
    assert state["active"] == (grant,) and state["blocked"] and not state["verifying"]
    rm.close()


@pytest.mark.anyio
async def test_late_verifier_cannot_suppress_timeout_into_success(tmp_path):
    adapter = SyntheticAdapter()
    rm = core(tmp_path, adapter, verification_timeout=0.02)
    await rm.recover("gpu-0")
    rm.submit(claim("a"))
    grant = await rm.wait("a")
    async def late(challenge):
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            return True
    adapter.verify = late
    with pytest.raises(AdmissionError):
        await rm.release(grant)
    assert rm.snapshot()["gpu-0"]["active"] == (grant,)
    assert rm.snapshot()["gpu-0"]["blocked"]
    rm.close()


@pytest.mark.anyio
@pytest.mark.parametrize("timeout", [True, 0, -1, float("inf"), float("nan"), None])
async def test_invalid_verification_timeout(tmp_path, timeout):
    with pytest.raises(ValueError):
        core(tmp_path, SyntheticAdapter(), verification_timeout=timeout)


@pytest.mark.anyio
async def test_verifier_cannot_suppress_caller_cancellation_into_release(tmp_path):
    adapter = SyntheticAdapter()
    rm = core(tmp_path, adapter)
    await rm.recover("gpu-0")
    rm.submit(claim("a"))
    grant = await rm.wait("a")
    entered = asyncio.Event()
    async def suppress(challenge):
        entered.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            return True
    adapter.verify = suppress
    task = asyncio.create_task(rm.release(grant))
    await entered.wait()
    task.cancel()
    with pytest.raises(AdmissionError):
        await task
    assert rm.snapshot()["gpu-0"]["active"] == (grant,)
    assert rm.snapshot()["gpu-0"]["blocked"]
    rm.close()
