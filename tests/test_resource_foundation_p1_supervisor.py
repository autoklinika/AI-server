"""Independent supervisor acceptance tests; no GPU, service or network access."""

import random
import socket
import subprocess
import time

import pytest
from pydantic import ValidationError

from ai_bridge.gateway.resource_accounting import (
    AssessmentClock,
    Attribution,
    Commitment,
    Demand,
    DeviceRequest,
    MemoryObservation,
    Observation,
    RefusalCode,
    ResourceRequest,
    ResourceSnapshot,
    assess_fit,
)
from ai_bridge.providers.accelerators import AcceleratorDescriptor, AcceleratorRegistry
from ai_bridge.providers.resource_topology import (
    Device,
    FaultDomain,
    InputCode,
    MemoryDomain,
    ResourceInputError,
    ResourceTopology,
)

GIB = 1024**3


def replace(model, **updates):
    return type(model).model_validate({**model.model_dump(), **updates})


def fixture(*, target="a", demand=GIB, second_capacity=48 * GIB):
    node = "ai-node-01"
    devices = tuple(
        Device(
            logical_id=key,
            physical_id="physical-" + key,
            generation=2,
            node_id=node,
            backend=backend,
            runtime_id=backend,
            ordinal=ordinal,
            memory_class=memory_class,
            memory_domain_id=domain,
        )
        for key, backend, ordinal, memory_class, domain in (
            ("u", "vulkan", 0, "unified", "host"),
            ("a", "cuda", 0, "dedicated", "va"),
            ("b", "cuda", 1, "dedicated", "vb"),
        )
    )
    domains = tuple(
        MemoryDomain(
            domain_id=key,
            node_id=node,
            kind=kind,
            generation=3,
            total_bytes=capacity,
            system_reserved_bytes=0,
        )
        for key, kind, capacity in (
            ("host", "host", 96 * GIB),
            ("va", "dedicated", 16 * GIB),
            ("vb", "dedicated", second_capacity),
        )
    )
    registry = AcceleratorRegistry(
        accelerators=tuple(
            AcceleratorDescriptor(
                accelerator_id=d.logical_id,
                node_id=node,
                kind="integrated" if d.memory_class == "unified" else "discrete",
                backend=d.backend,
                memory_class=d.memory_class,
                workload_classes=("llm",),
            )
            for d in devices
        )
    )
    topology = ResourceTopology(revision=11, devices=devices, domains=domains)
    snapshot = ResourceSnapshot(
        revision=7,
        topology_revision=11,
        epoch="boot-1",
        devices=tuple(
            Observation(
                resource_id=d.logical_id,
                generation=2,
                epoch="boot-1",
                observed_at_ns=1000,
                health="healthy",
            )
            for d in devices
        ),
        memory=tuple(
            MemoryObservation(
                resource_id=d.domain_id,
                generation=3,
                epoch="boot-1",
                observed_at_ns=1000,
                health="healthy",
                observed_used_bytes=0,
                attributed=(),
            )
            for d in domains
        ),
        faults=(),
        commitments=(),
    )
    device = next(d for d in devices if d.logical_id == target)
    request = ResourceRequest(
        node_id=node,
        expected_revision=7,
        topology_revision=11,
        epoch="boot-1",
        devices=(
            DeviceRequest(
                logical_id=device.logical_id,
                physical_id=device.physical_id,
                generation=device.generation,
                backend=device.backend,
                runtime_id=device.runtime_id,
            ),
        ),
        demands=(
            Demand(
                allocation_id="new", domain_id=device.memory_domain_id, bytes=demand
            ),
        ),
    )
    return dict(
        topology=topology,
        registry=registry,
        snapshot=snapshot,
        request=request,
        clock=AssessmentClock(epoch="boot-1", now_ns=1000, max_age_ns=100),
    )


def memory_case(
    *,
    capacity=16 * GIB,
    headroom=GIB,
    observed=6 * GIB,
    reserved=5 * GIB,
    attributed=2 * GIB,
    demand=6 * GIB,
    state="pending",
):
    inputs = fixture(demand=demand)
    inputs["topology"] = replace(
        inputs["topology"],
        domains=tuple(
            replace(d, total_bytes=capacity, system_reserved_bytes=headroom)
            if d.domain_id == "va"
            else d
            for d in inputs["topology"].domains
        ),
    )
    inputs["snapshot"] = replace(
        inputs["snapshot"],
        commitments=(
            Commitment(
                allocation_id="old",
                domain_id="va",
                reserved_bytes=reserved,
                state=state,
            ),
        ),
        memory=tuple(
            replace(
                m,
                observed_used_bytes=observed,
                attributed=(Attribution(allocation_id="old", bytes=attributed),),
            )
            if m.resource_id == "va"
            else m
            for m in inputs["snapshot"].memory
        ),
    )
    return inputs


@pytest.mark.parametrize("state", ["pending", "active", "uncertain"])
def test_independent_partial_loading_charged_once(state):
    result = assess_fit(**memory_case(state=state))
    assert result.fits and not result.authorizes_execution
    budget = result.proposal.budgets[0]
    assert (budget.external_bytes, budget.committed_bytes, budget.remaining_bytes) == (
        4 * GIB,
        5 * GIB,
        0,
    )


def test_independent_one_byte_over_refuses_whole_bundle():
    result = assess_fit(**memory_case(demand=6 * GIB + 1))
    assert not result.fits and result.proposal is None
    assert RefusalCode.INSUFFICIENT_CAPACITY in {d.code for d in result.diagnostics}


def test_independent_actual_usage_above_reservation_is_charged():
    result = assess_fit(
        **memory_case(observed=8 * GIB, attributed=7 * GIB, demand=7 * GIB)
    )
    assert result.fits
    assert result.proposal.budgets[0].remaining_bytes == 0
    assert result.proposal.budgets[0].committed_bytes == 7 * GIB


def test_independent_inconsistent_attribution_rejected():
    with pytest.raises(ResourceInputError):
        assess_fit(**memory_case(observed=GIB, attributed=2 * GIB))


def test_independent_uma_cpu_share_exact_host_budget():
    inputs = fixture(target="u", demand=22 * GIB)
    inputs["topology"] = replace(
        inputs["topology"],
        domains=tuple(
            replace(d, system_reserved_bytes=8 * GIB) if d.domain_id == "host" else d
            for d in inputs["topology"].domains
        ),
    )
    inputs["snapshot"] = replace(
        inputs["snapshot"],
        commitments=(
            Commitment(
                allocation_id="old",
                domain_id="host",
                reserved_bytes=32 * GIB,
                state="uncertain",
            ),
        ),
        memory=tuple(
            replace(
                m,
                observed_used_bytes=24 * GIB,
                attributed=(Attribution(allocation_id="old", bytes=10 * GIB),),
            )
            if m.resource_id == "host"
            else m
            for m in inputs["snapshot"].memory
        ),
    )
    inputs["request"] = replace(
        inputs["request"],
        demands=inputs["request"].demands
        + (Demand(allocation_id="cpu-buffer", domain_id="host", bytes=20 * GIB),),
    )
    result = assess_fit(**inputs)
    assert result.fits and len(result.proposal.budgets) == 1
    assert result.proposal.budgets[0].remaining_bytes == 0


@pytest.mark.parametrize("second_capacity", [8 * GIB, 24 * GIB, 48 * GIB, 96 * GIB])
def test_independent_vram_is_never_implicitly_pooled(second_capacity):
    assert not assess_fit(
        **fixture(demand=17 * GIB, second_capacity=second_capacity)
    ).fits


def test_independent_quarantine_a_does_not_block_b():
    inputs = fixture(target="b")
    inputs["snapshot"] = replace(
        inputs["snapshot"],
        devices=tuple(
            replace(d, health="quarantined") if d.resource_id == "a" else d
            for d in inputs["snapshot"].devices
        ),
    )
    assert assess_fit(**inputs).fits
    inputs["topology"] = replace(
        inputs["topology"],
        fault_domains=(FaultDomain(fault_domain_id="shared-link", generation=0),),
        devices=tuple(
            replace(d, fault_domain_id="shared-link")
            if d.logical_id in ("a", "b")
            else d
            for d in inputs["topology"].devices
        ),
    )
    inputs["snapshot"] = replace(
        inputs["snapshot"],
        faults=(
            Observation(
                resource_id="shared-link",
                generation=0,
                epoch="boot-1",
                observed_at_ns=1000,
                health="healthy",
            ),
        ),
    )
    assert not assess_fit(**inputs).fits


def test_independent_duplicate_physical_alias_rejected():
    inputs = fixture()
    inputs["topology"] = replace(
        inputs["topology"],
        devices=tuple(
            replace(d, physical_id="physical-a") if d.logical_id == "b" else d
            for d in inputs["topology"].devices
        ),
    )
    with pytest.raises(ResourceInputError):
        assess_fit(**inputs)


def test_independent_stale_epoch_and_generation_refused():
    inputs = fixture()
    inputs["clock"] = replace(inputs["clock"], epoch="boot-2")
    assert not assess_fit(**inputs).fits
    inputs = fixture()
    inputs["request"] = replace(
        inputs["request"],
        devices=(replace(inputs["request"].devices[0], generation=1),),
    )
    assert not assess_fit(**inputs).fits


def test_independent_permutation_and_ordinal_mapping_invariance():
    inputs = fixture()
    expected = assess_fit(**inputs)
    inputs["topology"] = replace(
        inputs["topology"],
        devices=tuple(
            replace(d, ordinal=1 - d.ordinal) if d.backend == "cuda" else d
            for d in reversed(inputs["topology"].devices)
        ),
        domains=tuple(reversed(inputs["topology"].domains)),
    )
    inputs["snapshot"] = replace(
        inputs["snapshot"],
        devices=tuple(reversed(inputs["snapshot"].devices)),
        memory=tuple(reversed(inputs["snapshot"].memory)),
    )
    assert assess_fit(**inputs) == expected


def test_independent_maximum_memory_id_still_returns_refusal():
    inputs = fixture(demand=17 * GIB)
    long_id = "m" * 256
    inputs["topology"] = replace(
        inputs["topology"],
        domains=tuple(
            replace(d, domain_id=long_id) if d.domain_id == "va" else d
            for d in inputs["topology"].domains
        ),
        devices=tuple(
            replace(d, memory_domain_id=long_id) if d.logical_id == "a" else d
            for d in inputs["topology"].devices
        ),
    )
    inputs["snapshot"] = replace(
        inputs["snapshot"],
        memory=tuple(
            replace(m, resource_id=long_id) if m.resource_id == "va" else m
            for m in inputs["snapshot"].memory
        ),
    )
    inputs["request"] = replace(
        inputs["request"],
        demands=(replace(inputs["request"].demands[0], domain_id=long_id),),
    )
    result = assess_fit(**inputs)
    assert not result.fits and result.proposal is None


def test_independent_host_node_must_exist_in_inventory():
    inputs = fixture()
    phantom = MemoryDomain(
        domain_id="phantom",
        node_id="unknown-node",
        kind="host",
        generation=3,
        total_bytes=96 * GIB,
        system_reserved_bytes=0,
    )
    inputs["topology"] = replace(
        inputs["topology"], domains=inputs["topology"].domains + (phantom,)
    )
    inputs["snapshot"] = replace(
        inputs["snapshot"],
        memory=inputs["snapshot"].memory
        + (
            MemoryObservation(
                resource_id="phantom",
                generation=3,
                epoch="boot-1",
                observed_at_ns=1000,
                health="healthy",
                observed_used_bytes=0,
                attributed=(),
            ),
        ),
    )
    inputs["request"] = replace(
        inputs["request"],
        node_id="unknown-node",
        devices=(),
        demands=(Demand(allocation_id="new", domain_id="phantom", bytes=GIB),),
    )
    with pytest.raises(ResourceInputError):
        assess_fit(**inputs)


def test_independent_boolean_or_implicit_execution_forbidden():
    result = assess_fit(**fixture())
    assert result.fits and result.authorizes_execution is False
    assert result.proposal.authorizes_execution is False
    with pytest.raises(TypeError):
        bool(result)
    with pytest.raises(TypeError):
        bool(result.proposal)
    with pytest.raises(ValidationError):
        Demand(allocation_id="new", domain_id="va", bytes=True)


def test_independent_arithmetic_conservation_randomized():
    rng = random.Random(20301030)
    for _ in range(200):
        capacity = rng.randint(16, 2048)
        headroom = rng.randint(0, capacity)
        observed = rng.randint(0, capacity)
        attributed = rng.randint(0, observed)
        reserved = rng.randint(0, capacity)
        demand = rng.randint(1, capacity + 1)
        inputs = memory_case(
            capacity=capacity,
            headroom=headroom,
            observed=observed,
            reserved=reserved,
            attributed=attributed,
            demand=demand,
        )
        expected = (
            capacity - headroom - observed - max(reserved - attributed, 0) - demand
        )
        result = assess_fit(**inputs)
        assert result.fits == (expected >= 0)
        if result.fits:
            budget = result.proposal.budgets[0]
            assert budget.remaining_bytes == expected
            assert (
                sum(
                    (
                        budget.system_reserved_bytes,
                        budget.external_bytes,
                        budget.committed_bytes,
                        budget.requested_bytes,
                        budget.remaining_bytes,
                    )
                )
                == capacity
            )


def test_independent_assessment_needs_no_io_or_clock_sampling(monkeypatch):
    inputs = fixture()
    before = {k: v.model_dump() for k, v in inputs.items()}

    def forbidden(*args, **kwargs):
        raise AssertionError("unexpected I/O or clock read")

    with monkeypatch.context() as m:
        m.setattr(socket, "create_connection", forbidden)
        m.setattr(subprocess, "Popen", forbidden)
        m.setattr(time, "monotonic", forbidden)
        m.setattr(time, "time", forbidden)
        result = assess_fit(**inputs)
    assert result.fits
    assert {k: v.model_dump() for k, v in inputs.items()} == before


@pytest.mark.parametrize("with_gpu", [False, True])
@pytest.mark.parametrize("capacity_class", ["unified", "host"])
@pytest.mark.parametrize("limit_descriptor_enabled", [False, True])
def test_peer_review_subset_cannot_inflate_host_memory(
    with_gpu, capacity_class, limit_descriptor_enabled
):
    """An omitted/disabled UMA or CPU descriptor still bounds physical host RAM."""
    inputs = fixture()
    inventory = inputs["registry"].accelerators
    if capacity_class == "unified":
        inventory = tuple(
            replace(d, total_memory_bytes=96 * GIB, enabled=limit_descriptor_enabled)
            if d.accelerator_id == "u"
            else d
            for d in inventory
        )
    else:
        inventory = inventory + (
            AcceleratorDescriptor(
                accelerator_id="host-cpu",
                node_id="ai-node-01",
                kind="virtual",
                backend="cpu",
                memory_class="host",
                total_memory_bytes=96 * GIB,
                workload_classes=("llm",),
                enabled=limit_descriptor_enabled,
            ),
        )
    inputs["registry"] = replace(inputs["registry"], accelerators=inventory)
    domain_ids = {"host", "va"} if with_gpu else {"host"}
    inputs["topology"] = replace(
        inputs["topology"],
        devices=tuple(
            d for d in inputs["topology"].devices if with_gpu and d.logical_id == "a"
        ),
        domains=tuple(
            replace(d, total_bytes=128 * GIB, system_reserved_bytes=8 * GIB)
            if d.domain_id == "host"
            else d
            for d in inputs["topology"].domains
            if d.domain_id in domain_ids
        ),
    )
    inputs["snapshot"] = replace(
        inputs["snapshot"],
        devices=tuple(
            d for d in inputs["snapshot"].devices if with_gpu and d.resource_id == "a"
        ),
        memory=tuple(
            d for d in inputs["snapshot"].memory if d.resource_id in domain_ids
        ),
    )
    inputs["request"] = replace(
        inputs["request"],
        devices=inputs["request"].devices if with_gpu else (),
        demands=(Demand(allocation_id="cpu", domain_id="host", bytes=120 * GIB),)
        + (inputs["request"].demands if with_gpu else ()),
    )
    with pytest.raises(ResourceInputError) as error:
        assess_fit(**inputs)
    assert error.value.code is InputCode.INVENTORY


def test_peer_review_host_bounds_do_not_borrow_dedicated_or_remote_limits():
    inputs = fixture(target="u", demand=80 * GIB)
    inventory = tuple(
        replace(d, total_memory_bytes=96 * GIB)
        if d.accelerator_id == "u"
        else replace(d, total_memory_bytes=16 * GIB)
        if d.accelerator_id == "a"
        else d
        for d in inputs["registry"].accelerators
    ) + (
        AcceleratorDescriptor(
            accelerator_id="remote-host",
            node_id="other-node",
            kind="virtual",
            backend="cpu",
            memory_class="host",
            total_memory_bytes=8 * GIB,
            workload_classes=("llm",),
        ),
    )
    inputs["registry"] = replace(inputs["registry"], accelerators=inventory)
    assert assess_fit(**inputs).fits
