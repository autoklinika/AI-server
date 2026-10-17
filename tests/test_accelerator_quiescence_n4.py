"""Synthetic CPU-only data. No reader, devices, services or GPU adapter."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import pytest

from ai_bridge.gateway.accelerator_evidence import PciIdentity
from ai_bridge.gateway.accelerator_quiescence import (
    Authority, Binding, Challenge, Closure, Evidence, Owner, QuiescenceAssessor,
    REQUIRED, Stage,
)


def sample(card=0, *, shared=True):
    owner = Owner("worker-a", 100, 42, "scope-a", 1, "lease-a", 1)
    survivor = Owner("worker-b", 200, 43, "scope-b", 1, "lease-b", 1)
    bdf = f"0000:0{card}:00.0"
    device = PciIdentity("11111111-1111-4111-8111-111111111111",
                         f"/sys/devices/pci0000:00/{bdf}", bdf, "0x1002", "0x150e")
    b = Binding(str(card) * 32, "epoch", device, 1, owner,
                "SHARED" if shared else "EXCLUSIVE", (survivor,) if shared else (), 1)
    c = Challenge(b, 1.0, 20.0)
    evidence = tuple(Evidence(b, s, a, "claimed-source", float(i + 2), True)
                     for i, (s, a) in enumerate(zip(Stage, REQUIRED)))
    closure = Closure(b, (owner,), True, True, True, True, 0, 0, 0, 0, 0, 0,
                      b.survivors, True)
    return c, evidence, closure


def assess(c, evidence, closure, **kwargs):
    assessor = QuiescenceAssessor("epoch")
    assessor.register(c)
    return assessor.assess(c.binding.nonce, evidence, closure,
                           current=kwargs.get("current", c.binding), now=kwargs.get("now", 8.0))


def denied(result):
    assert result.decision == "DENY"
    assert result.authorizes_release is False and result.authorizes_admission is False
    with pytest.raises(TypeError):
        bool(result)


@pytest.mark.parametrize("shared", [True, False])
def test_complete_structural_data_never_authorizes(shared):
    c, e, closure = sample(shared=shared)
    result = assess(c, e, closure)
    assert result.status == "ready_for_trusted_verification"
    denied(result)
    # Survivor activity is permitted: no global idle requirement in the schema.
    assert len(c.binding.survivors) == int(shared)


@pytest.mark.parametrize("field", [
    "process_readers_complete", "scope_sealed", "runtime_inventory_complete",
    "device_mapping_complete", "survivor_isolation_preserved",
    "unknown_submitters", "unsynchronized_streams", "pending_owner_work",
    "active_owner_contexts", "active_owner_fds", "deferred_owner_cleanup",
])
def test_unknown_reader_kfd_mapping_other_submitters_or_live_work(field):
    c, e, closure = sample()
    value = False if type(getattr(closure, field)) is bool else 1
    result = assess(c, e, replace(closure, **{field: value}))
    assert result.status == "unverified"
    denied(result)


@pytest.mark.parametrize("change", [
    {"birth_ticks": 99}, {"worker_id": "restarted"}, {"scope_generation": 2},
    {"lease_generation": 2}, {"pid": 101}, {"lease_id": "old"},
])
def test_stale_incarnation(change):
    c, e, closure = sample()
    current = replace(c.binding, owner=replace(c.binding.owner, **change))
    assert assess(c, e, closure, current=current).status == "unverified"


@pytest.mark.parametrize("change", [
    {"rm_epoch": "restarted"}, {"nonce": "f" * 32}, {"ownership_revision": 2},
    {"device_generation": 2}, {"survivors": ()}, {"mode": "EXCLUSIVE"},
])
def test_binding_mismatch(change):
    c, e, closure = sample()
    assert assess(c, e, closure, current=replace(c.binding, **change)).status == "unverified"


@pytest.mark.parametrize("change", [
    {"provenance": "TRUSTED"}, {"required_authority": Authority.RUNTIME},
    {"source_id": ""}, {"complete": False}, {"complete": 1},
    {"observed_at": 0}, {"observed_at": float("nan")}, {"observed_at": 9},
    {"stage": Stage.TEARDOWN},
])
def test_forged_cooperative_ack_cannot_be_upgraded(change):
    c, e, closure = sample()
    e = (replace(e[0], **change), *e[1:])
    result = assess(c, e, closure)
    assert result.status == "unverified"
    denied(result)


def test_partial_reordered_duplicate_and_cross_card_evidence():
    c, e, closure = sample()
    other, _, _ = sample(1)
    for records in (e[:-1], e[::-1], (e[0], *e[:-1]),
                    (replace(e[0], binding=other.binding), *e[1:])):
        assert assess(c, records, closure).status == "unverified"
    assert assess(c, e, closure, current=other.binding).status == "unverified"
    rebooted = replace(c.binding.device, boot_id="22222222-2222-4222-8222-222222222222")
    assert assess(c, e, closure, current=replace(c.binding, device=rebooted)).status == "unverified"


@pytest.mark.parametrize("now", [0, 20, 21, float("nan"), True, None])
def test_timeout_invalid_clock(now):
    c, e, closure = sample()
    assert assess(c, e, closure, now=now).status == "unverified"


def test_cancel_replay_restart_and_bounds():
    c, e, closure = sample()
    a = QuiescenceAssessor("epoch", capacity=1)
    a.register(c)
    a.cancel(c.binding.nonce)
    for _ in range(2):
        assert a.assess(c.binding.nonce, e, closure, current=c.binding, now=8).status == "unverified"
    with pytest.raises(ValueError):
        a.register(replace(c, binding=replace(c.binding, nonce="b" * 32)))
    restarted = QuiescenceAssessor("new-epoch")
    with pytest.raises(ValueError):
        restarted.register(c)
    assert restarted.assess(c.binding.nonce, e, closure, current=c.binding, now=8).status == "unverified"


def test_concurrent_double_release_and_cancel_always_deny():
    c, e, closure = sample()
    a = QuiescenceAssessor("epoch")
    a.register(c)
    def run(_):
        return a.assess(c.binding.nonce, e, closure, current=c.binding, now=8)
    with ThreadPoolExecutor(3) as pool:
        results = list(pool.map(run, range(2)))
        pool.submit(a.cancel, c.binding.nonce).result()
    assert sum(r.status == "ready_for_trusted_verification" for r in results) == 1
    for r in results:
        denied(r)


def test_two_devices_independent():
    a = QuiescenceAssessor("epoch")
    c0, e0, cl0 = sample(0)
    c1, e1, cl1 = sample(1)
    a.register(c0)
    a.register(c1)
    a.cancel(c0.binding.nonce)
    assert a.assess(c0.binding.nonce, e0, cl0, current=c0.binding, now=8).status == "unverified"
    result = a.assess(c1.binding.nonce, e1, cl1, current=c1.binding, now=8)
    assert result.status == "ready_for_trusted_verification"
    denied(result)


def test_descendant_scope_and_survivor_mixup():
    c, e, closure = sample()
    descendant = replace(c.binding.owner, pid=101, worker_id="child", lease_id="child")
    assert assess(c, e, replace(closure, members=(*closure.members, descendant))).status == "ready_for_trusted_verification"
    for members in ((), (descendant,), closure.members * 2,
                    (*closure.members, *c.binding.survivors)):
        assert assess(c, e, replace(closure, members=members)).status == "unverified"
    assert assess(c, e, replace(closure, survivors=())).status == "unverified"


@pytest.mark.parametrize("bad", [None, {}, (), True])
def test_malformed_input_fails_closed(bad):
    c, e, closure = sample()
    assert assess(c, e, bad).status == "unverified"
    assert assess(c, bad, closure).status == "unverified"
    assert assess(c, e, closure, current=bad).status == "unverified"


def test_malformed_challenges_rejected():
    c, _, _ = sample()
    for bad in (replace(c, deadline=float("inf")), replace(c, deadline=1000),
                replace(c, binding=replace(c.binding, device_generation=True)),
                replace(c, binding=replace(c.binding, device=replace(c.binding.device, bdf="kfd")))):
        with pytest.raises(ValueError):
            QuiescenceAssessor("epoch").register(bad)


def test_stale_closure_and_failed_attempt_are_consumed():
    c, e, closure = sample()
    a = QuiescenceAssessor("epoch")
    a.register(c)
    stale = replace(closure, binding=replace(c.binding, ownership_revision=0))
    assert a.assess(c.binding.nonce, e, stale, current=c.binding, now=8).status == "unverified"
    assert a.assess(c.binding.nonce, e, closure, current=c.binding, now=8).status == "unverified"


def test_self_reported_kernel_source_is_still_untrusted():
    c, evidence, closure = sample()
    evidence = tuple(replace(e, source_id="HTTP:kernel-certificate") for e in evidence)
    result = assess(c, evidence, closure)
    assert result.status == "ready_for_trusted_verification"
    denied(result)


def test_survivor_cannot_be_hidden_under_stale_identity():
    c, e, closure = sample()
    impostor = replace(c.binding.survivors[0], birth_ticks=999)
    assert assess(c, e, replace(closure, members=(*closure.members, impostor))).status == "unverified"
