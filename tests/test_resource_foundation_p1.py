"""Synthetic CPU-only evidence; these tests do not establish hardware safety."""

import builtins
import io
import itertools
import os
import random
import socket
import subprocess
import time
from pathlib import Path

import pytest
from pydantic import ValidationError

from ai_bridge.gateway import resource_accounting as accounting
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
from ai_bridge.providers import resource_topology as topology_module
from ai_bridge.providers.accelerators import (
    AcceleratorDescriptor,
    AcceleratorRegistry,
    local_accelerator_registry,
)
from ai_bridge.providers.resource_topology import (
    Device,
    FaultDomain,
    InputCode,
    MemoryDomain,
    ResourceInputError,
    ResourceTopology,
)

GiB = 1024**3


def changed(model, **updates):
    return type(model).model_validate({**model.model_dump(), **updates})


def replace_item(model, field, key, match_id, **updates):
    return changed(
        model,
        **{
            field: tuple(
                changed(item, **updates) if getattr(item, key) == match_id else item
                for item in getattr(model, field)
            )
        },
    )


def fixture(second_capacity=48 * GiB):
    """48 GiB is only a test parameter, never a claim about the planned RTX."""
    domains = tuple(
        MemoryDomain(
            domain_id=key,
            node_id="node-1",
            kind=kind,
            generation=3,
            total_bytes=capacity,
            system_reserved_bytes=headroom,
        )
        for key, kind, capacity, headroom in (
            ("host", "host", 96 * GiB, 8 * GiB),
            ("vram-a", "dedicated", 16 * GiB, GiB),
            ("vram-b", "dedicated", second_capacity, GiB),
        )
    )
    devices = tuple(
        Device(
            logical_id=key,
            physical_id=f"approved-uuid-{key}",
            generation=7,
            node_id="node-1",
            backend=backend,
            runtime_id=runtime,
            ordinal=ordinal,
            memory_class=memory_class,
            memory_domain_id=domain,
        )
        for key, backend, runtime, ordinal, memory_class, domain in (
            ("uma", "rocm", "hip-main", 0, "unified", "host"),
            ("a", "cuda", "cuda-main", 0, "dedicated", "vram-a"),
            ("b", "cuda", "cuda-main", 1, "dedicated", "vram-b"),
        )
    )
    topology = ResourceTopology(revision=4, devices=devices, domains=domains)
    registry = AcceleratorRegistry(
        accelerators=tuple(
            AcceleratorDescriptor(
                accelerator_id=device.logical_id,
                node_id=device.node_id,
                kind="integrated" if device.memory_class == "unified" else "discrete",
                backend=device.backend,
                memory_class=device.memory_class,
                total_memory_bytes=next(
                    d.total_bytes
                    for d in domains
                    if d.domain_id == device.memory_domain_id
                ),
                workload_classes=("llm",),
            )
            for device in devices
        )
    )
    snapshot = ResourceSnapshot(
        revision=12,
        topology_revision=4,
        epoch="boot-1",
        faults=(),
        commitments=(),
        devices=tuple(
            Observation(
                resource_id=d.logical_id,
                generation=d.generation,
                epoch="boot-1",
                observed_at_ns=950,
                health="healthy",
            )
            for d in devices
        ),
        memory=tuple(
            MemoryObservation(
                resource_id=d.domain_id,
                generation=d.generation,
                epoch="boot-1",
                observed_at_ns=950,
                health="healthy",
                observed_used_bytes=0,
                attributed=(),
            )
            for d in domains
        ),
    )
    clock = AssessmentClock(epoch="boot-1", now_ns=1000, max_age_ns=100)
    return topology, registry, snapshot, clock


def request_for(topology, snapshot, ids=("a",), demands=None):
    devices = {d.logical_id: d for d in topology.devices}
    return ResourceRequest(
        node_id="node-1",
        expected_revision=snapshot.revision,
        topology_revision=topology.revision,
        epoch=snapshot.epoch,
        devices=tuple(
            DeviceRequest(
                logical_id=key,
                physical_id=devices[key].physical_id,
                generation=devices[key].generation,
                backend=devices[key].backend,
                runtime_id=devices[key].runtime_id,
            )
            for key in ids
        ),
        demands=demands
        if demands is not None
        else tuple(
            Demand(
                allocation_id=f"new-{key}",
                domain_id=devices[key].memory_domain_id,
                bytes=GiB,
            )
            for key in ids
        ),
    )


def evaluate(topology, registry, snapshot, clock, request=None):
    return assess_fit(
        topology,
        registry,
        snapshot,
        request if request is not None else request_for(topology, snapshot),
        clock,
    )


def assert_refused(result, code):
    assert result.fits is False
    assert result.proposal is None
    assert result.authorizes_execution is False
    assert code in {item.code for item in result.diagnostics}
    assert result.diagnostics == tuple(
        sorted(
            result.diagnostics,
            key=lambda item: (item.code, item.resource_id),
        )
    )


@pytest.mark.parametrize("second_gib", [8, 24, 48, 80])
def test_parameterized_second_rtx_exact_limit(second_gib):
    topology, registry, snapshot, clock = fixture(second_gib * GiB)
    demand = Demand(
        allocation_id="model", domain_id="vram-b", bytes=(second_gib - 1) * GiB
    )
    request = request_for(topology, snapshot, ("b",), (demand,))
    result = evaluate(topology, registry, snapshot, clock, request)
    assert result.fits is True
    assert result.proposal.budgets[0].remaining_bytes == 0
    assert result.proposal.authorizes_execution is False
    for value in (result, result.proposal):
        with pytest.raises(TypeError):
            bool(value)
    request = changed(request, demands=(changed(demand, bytes=demand.bytes + 1),))
    assert_refused(
        evaluate(topology, registry, snapshot, clock, request),
        RefusalCode.INSUFFICIENT_CAPACITY,
    )


def test_dedicated_vram_cannot_be_pooled_and_failure_is_atomic():
    topology, registry, snapshot, clock = fixture()
    request = request_for(
        topology,
        snapshot,
        ("a", "b"),
        (
            Demand(allocation_id="model-a", domain_id="vram-a", bytes=16 * GiB),
            Demand(allocation_id="model-b", domain_id="vram-b", bytes=GiB),
        ),
    )
    result = evaluate(topology, registry, snapshot, clock, request)
    assert_refused(result, RefusalCode.INSUFFICIENT_CAPACITY)
    assert result.diagnostics[0].resource_id == "memory:vram-a"
    assert "budgets" not in result.model_dump()
    with pytest.raises(TypeError):
        bool(result)


def test_uma_and_separate_cpu_buffer_share_one_host_budget():
    topology, registry, snapshot, clock = fixture()
    shared = Demand(allocation_id="shared-model", domain_id="host", bytes=80 * GiB)
    cpu = Demand(allocation_id="cpu-buffer", domain_id="host", bytes=8 * GiB)
    request = request_for(topology, snapshot, ("uma",), (shared, cpu))
    result = evaluate(topology, registry, snapshot, clock, request)
    assert result.proposal.budgets[0].requested_bytes == 88 * GiB
    assert result.proposal.budgets[0].remaining_bytes == 0
    assert_refused(
        evaluate(
            topology,
            registry,
            snapshot,
            clock,
            changed(
                request,
                demands=(shared, changed(cpu, bytes=cpu.bytes + 1)),
            ),
        ),
        RefusalCode.INSUFFICIENT_CAPACITY,
    )
    cpu_only = request_for(topology, snapshot, (), (cpu,))
    assert evaluate(topology, registry, snapshot, clock, cpu_only).fits


@pytest.mark.parametrize("conflicting", [False, True])
def test_canonical_uma_demands_reject_even_identical_duplicates(conflicting):
    topology, registry, snapshot, clock = fixture()
    demand = Demand(allocation_id="shared", domain_id="host", bytes=GiB)
    request = request_for(
        topology,
        snapshot,
        ("uma",),
        (
            demand,
            changed(demand, bytes=2 * GiB) if conflicting else demand,
        ),
    )
    with pytest.raises(ResourceInputError) as caught:
        evaluate(topology, registry, snapshot, clock, request)
    assert caught.value.code == InputCode.DUPLICATE


@pytest.mark.parametrize(
    "ids,domain", [(("a",), "vram-b"), ((), "vram-a"), (("a",), "host")]
)
def test_gpu_requires_its_own_positive_domain_demand(ids, domain):
    topology, registry, snapshot, clock = fixture()
    request = request_for(
        topology,
        snapshot,
        ids,
        (Demand(allocation_id="new", domain_id=domain, bytes=GiB),),
    )
    with pytest.raises(ResourceInputError) as caught:
        evaluate(topology, registry, snapshot, clock, request)
    assert caught.value.code == InputCode.BINDING


def test_host_ancillary_demand_is_local_and_separate():
    topology, registry, snapshot, clock = fixture()
    request = request_for(topology, snapshot)
    local = Demand(allocation_id="cpu", domain_id="host", bytes=GiB)
    request = changed(request, demands=(*request.demands, local))
    assert (
        len(evaluate(topology, registry, snapshot, clock, request).proposal.budgets)
        == 2
    )
    remote = changed(topology.domains[0], domain_id="remote-host", node_id="node-2")
    topology = changed(topology, domains=(*topology.domains, remote))
    registry = changed(
        registry,
        accelerators=(
            *registry.accelerators,
            changed(
                registry.accelerators[0],
                accelerator_id="remote-uma",
                node_id="node-2",
            ),
        ),
    )
    request = changed(
        request, demands=(*request.demands, changed(local, domain_id="remote-host"))
    )
    with pytest.raises(ResourceInputError) as caught:
        evaluate(topology, registry, snapshot, clock, request)
    assert caught.value.code == InputCode.BINDING


@pytest.mark.parametrize(
    "field,value",
    [
        ("logical_id", "a"),
        ("physical_id", "approved-uuid-a"),
        ("ordinal", 0),
    ],
)
def test_duplicate_device_identities_and_runtime_ordinals(field, value):
    topology, registry, _, _ = fixture()
    topology = replace_item(topology, "devices", "logical_id", "b", **{field: value})
    with pytest.raises(ResourceInputError) as caught:
        topology.validate_against(registry)
    assert caught.value.code == InputCode.DUPLICATE


def test_distinct_runtimes_may_each_use_ordinal_zero():
    topology, registry, snapshot, clock = fixture()
    topology = replace_item(
        topology, "devices", "logical_id", "b", runtime_id="cuda-other", ordinal=0
    )
    request = request_for(topology, snapshot, ("a", "b", "uma"))
    assert evaluate(topology, registry, snapshot, clock, request).fits


def test_host_node_must_exist_in_logical_inventory():
    topology, registry, _, _ = fixture()
    host = changed(
        topology.domains[0], domain_id="unregistered-host", node_id="missing-node"
    )
    topology = changed(topology, domains=(*topology.domains, host))
    with pytest.raises(ResourceInputError) as caught:
        topology.validate_against(registry)
    assert caught.value.code == InputCode.REFERENCE


@pytest.mark.parametrize(
    "update",
    [
        {"memory_domain_id": "missing"},
        {"fault_domain_id": "missing"},
        {"memory_domain_id": "host"},
        {"memory_domain_id": "vram-a"},
        {"node_id": "elsewhere"},
        {"backend": "vulkan"},
    ],
)
def test_invalid_topology_references_and_binding(update):
    topology, registry, _, _ = fixture()
    topology = replace_item(topology, "devices", "logical_id", "b", **update)
    with pytest.raises(ResourceInputError):
        topology.validate_against(registry)


@pytest.mark.parametrize(
    "case",
    [
        "duplicate-host",
        "duplicate-domain",
        "orphan-vram",
        "fault-ref",
        "duplicate-fault",
    ],
)
def test_domain_structure_rejects_ambiguous_aliases(case):
    topology, registry, _, _ = fixture()
    if case == "duplicate-host":
        topology = changed(
            topology,
            domains=(
                *topology.domains,
                changed(topology.domains[0], domain_id="host2"),
            ),
        )
    elif case == "duplicate-domain":
        topology = changed(topology, domains=(*topology.domains, topology.domains[0]))
    elif case == "orphan-vram":
        topology = changed(
            topology,
            domains=(
                *topology.domains,
                changed(topology.domains[1], domain_id="orphan"),
            ),
        )
    elif case == "fault-ref":
        topology = replace_item(
            topology, "domains", "domain_id", "host", fault_domain_id="missing"
        )
    else:
        fault = FaultDomain(fault_domain_id="shared-reset", generation=1)
        topology = changed(topology, fault_domains=(fault, fault))
    with pytest.raises(ResourceInputError):
        topology.validate_against(registry)


@pytest.mark.parametrize(
    "updates",
    [
        {"enabled": False},
        {"node_id": "other-node"},
        {"backend": "vulkan"},
        {"backend": "unknown"},
        {"memory_class": "unified"},
        {"total_memory_bytes": 15 * GiB},
        {"accelerator_id": "different-id"},
    ],
)
def test_logical_inventory_boundary(updates):
    topology, registry, _, _ = fixture()
    registry = replace_item(registry, "accelerators", "accelerator_id", "a", **updates)
    with pytest.raises(ResourceInputError) as caught:
        topology.validate_against(registry)
    assert caught.value.code == InputCode.INVENTORY


def test_unknown_n0_stays_usable_but_does_not_become_eligible():
    topology, _, snapshot, clock = fixture()
    registry = local_accelerator_registry(node_id="node-1")
    assert registry.candidates("ollama-local")
    device = changed(topology.devices[0], logical_id="local-primary")
    topology = changed(topology, devices=(device,), domains=(topology.domains[0],))
    with pytest.raises(ResourceInputError) as caught:
        topology.validate_against(registry)
    assert caught.value.code == InputCode.INVENTORY
    topology, registry, snapshot, clock = fixture()
    registry = replace_item(
        registry, "accelerators", "accelerator_id", "a", total_memory_bytes=None
    )
    assert evaluate(topology, registry, snapshot, clock).fits
    topology = replace_item(
        topology, "domains", "domain_id", "vram-a", total_bytes=None
    )
    assert_refused(
        evaluate(topology, registry, snapshot, clock), RefusalCode.MISSING_CAPACITY
    )


@pytest.mark.parametrize(
    "field,value,code",
    [
        ("generation", 6, RefusalCode.GENERATION),
        ("physical_id", "different-uuid", RefusalCode.DEVICE_MISMATCH),
        ("backend", "vulkan", RefusalCode.DEVICE_MISMATCH),
        ("runtime_id", "other", RefusalCode.DEVICE_MISMATCH),
    ],
)
def test_request_must_match_current_device(field, value, code):
    topology, registry, snapshot, clock = fixture()
    request = request_for(topology, snapshot)
    request = changed(request, devices=(changed(request.devices[0], **{field: value}),))
    assert_refused(evaluate(topology, registry, snapshot, clock, request), code)


@pytest.mark.parametrize(
    "target,field,value,code",
    [
        ("request", "expected_revision", 11, RefusalCode.REVISION),
        ("request", "topology_revision", 3, RefusalCode.REVISION),
        ("snapshot", "topology_revision", 3, RefusalCode.REVISION),
        ("snapshot", "revision", 13, RefusalCode.REVISION),
        ("request", "epoch", "old-boot", RefusalCode.CLOCK_EPOCH),
        ("snapshot", "epoch", "old-boot", RefusalCode.CLOCK_EPOCH),
        ("clock", "epoch", "new-boot", RefusalCode.CLOCK_EPOCH),
    ],
)
def test_revisions_and_clock_epoch(target, field, value, code):
    topology, registry, snapshot, clock = fixture()
    request = request_for(topology, snapshot)
    values = {"request": request, "snapshot": snapshot, "clock": clock}
    values[target] = changed(values[target], **{field: value})
    assert_refused(
        evaluate(
            topology, registry, values["snapshot"], values["clock"], values["request"]
        ),
        code,
    )


@pytest.mark.parametrize("collection,key", [("devices", "a"), ("memory", "vram-a")])
@pytest.mark.parametrize(
    "updates,code",
    [
        ({"generation": 0}, RefusalCode.GENERATION),
        ({"epoch": "previous-boot"}, RefusalCode.CLOCK_EPOCH),
        ({"observed_at_ns": 899}, RefusalCode.STALE),
        ({"observed_at_ns": 1001}, RefusalCode.FUTURE),
        ({"health": "unknown"}, RefusalCode.UNHEALTHY),
        ({"health": "busy"}, RefusalCode.UNHEALTHY),
        ({"health": "quarantined"}, RefusalCode.UNHEALTHY),
        ({"health": "unavailable"}, RefusalCode.UNHEALTHY),
    ],
)
def test_required_device_and_memory_telemetry(collection, key, updates, code):
    topology, registry, snapshot, clock = fixture()
    snapshot = replace_item(snapshot, collection, "resource_id", key, **updates)
    assert_refused(evaluate(topology, registry, snapshot, clock), code)


@pytest.mark.parametrize("collection", ["devices", "memory"])
def test_missing_samples_and_exact_freshness_boundary(collection):
    topology, registry, snapshot, clock = fixture()
    snapshot = changed(
        snapshot,
        **{
            collection: tuple(
                changed(x, observed_at_ns=900) for x in getattr(snapshot, collection)
            )
        },
    )
    assert evaluate(topology, registry, snapshot, clock).fits
    snapshot = changed(snapshot, **{collection: ()})
    assert_refused(
        evaluate(topology, registry, snapshot, clock), RefusalCode.MISSING_TELEMETRY
    )


def test_unknown_memory_observation_is_not_zero():
    topology, registry, snapshot, clock = fixture()
    snapshot = replace_item(
        snapshot, "memory", "resource_id", "vram-a", observed_used_bytes=None
    )
    assert_refused(
        evaluate(topology, registry, snapshot, clock), RefusalCode.MISSING_TELEMETRY
    )


@pytest.mark.parametrize("health", ["busy", "quarantined", "unknown", "unavailable"])
def test_unhealthy_a_does_not_refuse_healthy_b(health):
    topology, registry, snapshot, clock = fixture()
    snapshot = replace_item(snapshot, "devices", "resource_id", "a", health=health)
    snapshot = replace_item(snapshot, "memory", "resource_id", "vram-a", health=health)
    request = request_for(topology, snapshot, ("b",))
    assert evaluate(topology, registry, snapshot, clock, request).fits
    topology = replace_item(
        topology, "domains", "domain_id", "vram-a", total_bytes=None
    )
    snapshot = changed(
        snapshot, devices=tuple(d for d in snapshot.devices if d.resource_id != "a")
    )
    assert evaluate(topology, registry, snapshot, clock, request).fits


def fault_fixture():
    topology, registry, snapshot, clock = fixture()
    topology = changed(
        topology,
        fault_domains=(FaultDomain(fault_domain_id="reset", generation=2),),
        devices=tuple(
            changed(d, fault_domain_id="reset") if d.logical_id in ("a", "b") else d
            for d in topology.devices
        ),
    )
    snapshot = changed(
        snapshot,
        faults=(
            Observation(
                resource_id="reset",
                generation=2,
                epoch="boot-1",
                observed_at_ns=950,
                health="healthy",
            ),
        ),
    )
    return topology, registry, snapshot, clock


@pytest.mark.parametrize(
    "case,code",
    [
        ("member", RefusalCode.UNHEALTHY),
        ("group", RefusalCode.UNHEALTHY),
        ("missing", RefusalCode.MISSING_TELEMETRY),
        ("generation", RefusalCode.GENERATION),
        ("epoch", RefusalCode.CLOCK_EPOCH),
        ("old", RefusalCode.STALE),
        ("future", RefusalCode.FUTURE),
    ],
)
def test_explicit_shared_fault_domain_requires_all_members(case, code):
    topology, registry, snapshot, clock = fault_fixture()
    request = request_for(topology, snapshot, ("b",))
    assert evaluate(topology, registry, snapshot, clock, request).fits
    if case == "member":
        snapshot = replace_item(
            snapshot, "devices", "resource_id", "a", health="quarantined"
        )
    elif case == "missing":
        snapshot = changed(snapshot, faults=())
    else:
        updates = {
            "group": {"health": "quarantined"},
            "generation": {"generation": 1},
            "epoch": {"epoch": "previous-boot"},
            "old": {"observed_at_ns": 899},
            "future": {"observed_at_ns": 1001},
        }[case]
        snapshot = changed(snapshot, faults=(changed(snapshot.faults[0], **updates),))
    assert_refused(evaluate(topology, registry, snapshot, clock, request), code)


def test_host_health_affects_uma_and_cpu_without_inventing_gpu_fault_group():
    topology, registry, snapshot, clock = fixture()
    cpu = request_for(
        topology,
        snapshot,
        (),
        (Demand(allocation_id="cpu", domain_id="host", bytes=GiB),),
    )
    snapshot = replace_item(
        snapshot, "devices", "resource_id", "uma", health="quarantined"
    )
    assert evaluate(topology, registry, snapshot, clock, cpu).fits
    snapshot = replace_item(
        snapshot, "memory", "resource_id", "host", health="quarantined"
    )
    assert_refused(
        evaluate(topology, registry, snapshot, clock, cpu), RefusalCode.UNHEALTHY
    )
    assert_refused(
        evaluate(
            topology,
            registry,
            snapshot,
            clock,
            request_for(topology, snapshot, ("uma",)),
        ),
        RefusalCode.UNHEALTHY,
    )
    assert evaluate(topology, registry, snapshot, clock).fits


@pytest.mark.parametrize("unknown_capacity", [False, True])
def test_shared_fault_memory_member_requires_complete_telemetry(unknown_capacity):
    topology, registry, snapshot, clock = fault_fixture()
    topology = changed(
        topology,
        domains=tuple(
            changed(d, fault_domain_id="reset") if d.kind == "dedicated" else d
            for d in topology.domains
        ),
    )
    request = request_for(topology, snapshot, ("b",))
    assert evaluate(topology, registry, snapshot, clock, request).fits
    if unknown_capacity:
        topology = replace_item(
            topology, "domains", "domain_id", "vram-a", total_bytes=None
        )
    else:
        snapshot = replace_item(
            snapshot, "memory", "resource_id", "vram-a", observed_used_bytes=None
        )
    assert_refused(
        evaluate(topology, registry, snapshot, clock, request),
        RefusalCode.MISSING_CAPACITY
        if unknown_capacity
        else RefusalCode.MISSING_TELEMETRY,
    )


def test_all_required_resources_are_checked_before_atomic_refusal():
    topology, registry, snapshot, clock = fixture()
    request = request_for(topology, snapshot, ("a", "b", "uma"))
    snapshot = replace_item(snapshot, "devices", "resource_id", "a", generation=1)
    snapshot = replace_item(
        snapshot, "devices", "resource_id", "b", health="quarantined"
    )
    snapshot = replace_item(
        snapshot, "memory", "resource_id", "host", observed_at_ns=1001
    )
    snapshot = replace_item(
        snapshot, "memory", "resource_id", "vram-a", observed_at_ns=899
    )
    snapshot = replace_item(
        snapshot, "memory", "resource_id", "vram-b", observed_used_bytes=48 * GiB
    )
    result = evaluate(topology, registry, snapshot, clock, request)
    assert result.proposal is None
    assert {(item.code, item.resource_id) for item in result.diagnostics} == {
        (RefusalCode.GENERATION, "device:a"),
        (RefusalCode.UNHEALTHY, "device:b"),
        (RefusalCode.FUTURE, "memory:host"),
        (RefusalCode.STALE, "memory:vram-a"),
        (RefusalCode.INSUFFICIENT_CAPACITY, "memory:vram-b"),
    }


def test_maximum_length_domain_id_still_returns_a_refusal():
    topology, registry, snapshot, clock = fixture()
    long_id = "d" * 256
    topology = replace_item(
        topology, "domains", "domain_id", "vram-a", domain_id=long_id
    )
    topology = replace_item(
        topology, "devices", "logical_id", "a", memory_domain_id=long_id
    )
    snapshot = replace_item(
        snapshot,
        "memory",
        "resource_id",
        "vram-a",
        resource_id=long_id,
        health="unknown",
    )
    assert_refused(evaluate(topology, registry, snapshot, clock), RefusalCode.UNHEALTHY)


@pytest.mark.parametrize("state", ["pending", "active", "uncertain"])
def test_partial_loading_and_unrelated_external_usage(state):
    topology, registry, snapshot, clock = fixture()
    snapshot = changed(
        snapshot,
        commitments=(
            Commitment(
                allocation_id="loading",
                domain_id="vram-a",
                reserved_bytes=8 * GiB,
                state=state,
            ),
        ),
    )
    snapshot = replace_item(
        snapshot,
        "memory",
        "resource_id",
        "vram-a",
        observed_used_bytes=6 * GiB,
        attributed=(Attribution(allocation_id="loading", bytes=3 * GiB),),
    )
    demand = Demand(allocation_id="new", domain_id="vram-a", bytes=4 * GiB)
    request = request_for(topology, snapshot, demands=(demand,))
    result = evaluate(topology, registry, snapshot, clock, request)
    budget = result.proposal.budgets[0]
    assert (budget.external_bytes, budget.committed_bytes, budget.remaining_bytes) == (
        3 * GiB,
        8 * GiB,
        0,
    )
    assert_refused(
        evaluate(
            topology,
            registry,
            snapshot,
            clock,
            changed(
                request,
                demands=(changed(demand, bytes=4 * GiB + 1),),
            ),
        ),
        RefusalCode.INSUFFICIENT_CAPACITY,
    )


def test_over_reservation_attribution_and_pending_uncertain_are_all_charged():
    topology, registry, snapshot, clock = fixture()
    snapshot = changed(
        snapshot,
        commitments=tuple(
            Commitment(
                allocation_id=key,
                domain_id="vram-a",
                reserved_bytes=amount * GiB,
                state=state,
            )
            for key, amount, state in (
                ("over", 1, "active"),
                ("waiting", 4, "pending"),
                ("lost", 5, "uncertain"),
            )
        ),
    )
    snapshot = replace_item(
        snapshot,
        "memory",
        "resource_id",
        "vram-a",
        observed_used_bytes=5 * GiB,
        attributed=(Attribution(allocation_id="over", bytes=3 * GiB),),
    )
    result = evaluate(topology, registry, snapshot, clock)
    budget = result.proposal.budgets[0]
    assert budget.committed_bytes == 12 * GiB
    assert budget.external_bytes == 2 * GiB
    assert budget.remaining_bytes == 0
    snapshot = replace_item(snapshot, "memory", "resource_id", "vram-a", attributed=())
    assert_refused(
        evaluate(topology, registry, snapshot, clock), RefusalCode.INSUFFICIENT_CAPACITY
    )


@pytest.mark.parametrize(
    "case", ["duplicate", "conflict", "new-reuses", "bad-domain", "unknown-state"]
)
def test_commitment_keys_and_states(case):
    topology, registry, snapshot, clock = fixture()
    existing = Commitment(
        allocation_id="old", domain_id="vram-a", reserved_bytes=GiB, state="uncertain"
    )
    request = request_for(topology, snapshot)
    if case == "unknown-state":
        with pytest.raises(ValidationError):
            changed(existing, state="released")
        return
    entries = (existing,)
    if case in ("duplicate", "conflict"):
        entries += (
            changed(existing, reserved_bytes=2 * GiB)
            if case == "conflict"
            else existing,
        )
    elif case == "new-reuses":
        request = changed(
            request, demands=(changed(request.demands[0], allocation_id="old"),)
        )
    else:
        entries = (changed(existing, domain_id="absent"),)
    snapshot = changed(snapshot, commitments=entries)
    with pytest.raises(ResourceInputError) as caught:
        evaluate(topology, registry, snapshot, clock, request)
    assert (
        caught.value.code
        == {
            "duplicate": InputCode.DUPLICATE,
            "conflict": InputCode.DUPLICATE,
            "new-reuses": InputCode.REUSED_ALLOCATION,
            "bad-domain": InputCode.REFERENCE,
        }[case]
    )


def test_same_allocation_id_in_distinct_domains_is_charged_separately():
    topology, registry, snapshot, clock = fixture()
    domains = ("vram-a", "vram-b")
    snapshot = changed(
        snapshot,
        commitments=tuple(
            Commitment(
                allocation_id="old",
                domain_id=domain,
                reserved_bytes=2 * GiB,
                state="pending",
            )
            for domain in domains
        ),
    )
    request = request_for(
        topology,
        snapshot,
        ("a", "b"),
        tuple(
            Demand(
                allocation_id="new",
                domain_id=domain,
                bytes=GiB,
            )
            for domain in domains
        ),
    )
    result = evaluate(topology, registry, snapshot, clock, request)
    assert tuple(b.committed_bytes for b in result.proposal.budgets) == (
        2 * GiB,
        2 * GiB,
    )
    assert tuple(b.requested_bytes for b in result.proposal.budgets) == (GiB, GiB)


@pytest.mark.parametrize(
    "case,code",
    [
        ("duplicate-device", InputCode.DUPLICATE),
        ("unknown-device", InputCode.REFERENCE),
        ("unknown-domain", InputCode.REFERENCE),
        ("remote-node", InputCode.BINDING),
    ],
)
def test_invalid_request_references(case, code):
    topology, registry, snapshot, clock = fixture()
    request = request_for(topology, snapshot)
    if case == "duplicate-device":
        request = changed(request, devices=(*request.devices, *request.devices))
    elif case == "unknown-device":
        request = changed(
            request, devices=(changed(request.devices[0], logical_id="missing"),)
        )
    elif case == "unknown-domain":
        request = changed(
            request, demands=(changed(request.demands[0], domain_id="missing"),)
        )
    else:
        request = changed(request, node_id="remote-node")
    with pytest.raises(ResourceInputError) as caught:
        evaluate(topology, registry, snapshot, clock, request)
    assert caught.value.code == code


def test_aggregate_attribution_cannot_exceed_observed_usage():
    topology, registry, snapshot, clock = fixture()
    snapshot = changed(
        snapshot,
        commitments=tuple(
            Commitment(
                allocation_id=key,
                domain_id="vram-a",
                reserved_bytes=5 * GiB,
                state="active",
            )
            for key in ("x", "y")
        ),
    )
    snapshot = replace_item(
        snapshot,
        "memory",
        "resource_id",
        "vram-a",
        observed_used_bytes=6 * GiB,
        attributed=tuple(
            Attribution(allocation_id=key, bytes=4 * GiB) for key in ("x", "y")
        ),
    )
    with pytest.raises(ResourceInputError) as caught:
        evaluate(topology, registry, snapshot, clock)
    assert caught.value.code == InputCode.ATTRIBUTION


@pytest.mark.parametrize(
    "case",
    [
        "unknown-id",
        "wrong-domain",
        "duplicate",
        "sum-too-big",
        "used-too-big",
        "unknown-used",
    ],
)
def test_inconsistent_attribution_is_rejected_even_on_unselected_domain(case):
    topology, registry, snapshot, clock = fixture()
    commitment = Commitment(
        allocation_id="old", domain_id="vram-a", reserved_bytes=GiB, state="active"
    )
    snapshot = changed(snapshot, commitments=(commitment,))
    attribution = Attribution(allocation_id="old", bytes=GiB)
    updates = {"observed_used_bytes": GiB, "attributed": (attribution,)}
    domain = "vram-a"
    if case == "unknown-id":
        updates["attributed"] = (changed(attribution, allocation_id="unknown"),)
    elif case == "wrong-domain":
        domain = "vram-b"
    elif case == "duplicate":
        updates["attributed"] = (attribution, attribution)
    elif case == "sum-too-big":
        updates["observed_used_bytes"] = GiB - 1
    elif case == "used-too-big":
        updates["observed_used_bytes"] = 17 * GiB
    else:
        updates["observed_used_bytes"] = None
    snapshot = replace_item(snapshot, "memory", "resource_id", domain, **updates)
    with pytest.raises(ResourceInputError):
        evaluate(
            topology, registry, snapshot, clock, request_for(topology, snapshot, ("b",))
        )


@pytest.mark.parametrize("collection", ["devices", "memory", "faults"])
@pytest.mark.parametrize("duplicate", [False, True])
def test_snapshot_sample_keys(collection, duplicate):
    topology, registry, snapshot, clock = fault_fixture()
    sample = getattr(snapshot, collection)[0]
    snapshot = changed(
        snapshot,
        **{
            collection: (
                *getattr(snapshot, collection),
                sample if duplicate else changed(sample, resource_id="missing"),
            )
        },
    )
    with pytest.raises(ResourceInputError) as caught:
        evaluate(topology, registry, snapshot, clock)
    assert caught.value.code == (
        InputCode.DUPLICATE if duplicate else InputCode.REFERENCE
    )


@pytest.mark.parametrize(
    "value",
    [
        True,
        False,
        -1,
        1.0,
        1.5,
        float("inf"),
        float("-inf"),
        float("nan"),
        "1",
        b"1",
        None,
    ],
)
def test_strict_numeric_fields_reject_coercion(value):
    topology, _, snapshot, clock = fixture()
    demand = Demand(allocation_id="new", domain_id="host", bytes=1)
    for model, field in (
        (demand, "bytes"),
        (topology.devices[0], "generation"),
        (topology.devices[0], "ordinal"),
        (clock, "now_ns"),
        (clock, "max_age_ns"),
        (snapshot, "revision"),
        (snapshot.memory[0], "observed_at_ns"),
        (topology.domains[0], "system_reserved_bytes"),
        (Attribution(allocation_id="old", bytes=1), "bytes"),
        (
            Commitment(
                allocation_id="old", domain_id="host", reserved_bytes=1, state="pending"
            ),
            "reserved_bytes",
        ),
    ):
        with pytest.raises(ValidationError):
            changed(model, **{field: value})
    if (
        value is not None
    ):  # None is an explicit missing value, never an eligible capacity/measurement.
        for model, field in (
            (topology.domains[0], "total_bytes"),
            (snapshot.memory[0], "observed_used_bytes"),
        ):
            with pytest.raises(ValidationError):
                changed(model, **{field: value})


@pytest.mark.parametrize("value", [[], {}, set(), "", None, 1])
def test_strict_nested_containers(value):
    topology, _, snapshot, _ = fixture()
    request = request_for(topology, snapshot)
    for model, field in (
        (topology, "devices"),
        (topology, "domains"),
        (snapshot, "commitments"),
        (snapshot, "devices"),
        (snapshot, "memory"),
        (snapshot.memory[0], "attributed"),
        (request, "devices"),
        (request, "demands"),
    ):
        with pytest.raises(ValidationError):
            changed(model, **{field: value})


def test_missing_identity_zero_demand_extra_fields_and_bad_nested_input():
    topology, _, snapshot, _ = fixture()
    for value in ("", " ", "has space", None, 12):
        with pytest.raises(ValidationError):
            changed(topology.devices[0], physical_id=value)
    with pytest.raises(ValidationError):
        Demand(allocation_id="x", domain_id="host", bytes=0)
    with pytest.raises(ValidationError):
        changed(topology.domains[0], total_bytes=0)
    with pytest.raises(ValidationError):
        changed(topology.domains[0], system_reserved_bytes=97 * GiB)
    with pytest.raises(ValidationError):
        changed(snapshot, surprising=True)
    with pytest.raises(ValidationError):
        changed(snapshot, devices=(object(),))
    with pytest.raises(ValidationError):
        changed(request_for(topology, snapshot), demands=())


def test_unsafe_pydantic_copies_are_revalidated_at_assessment_boundary():
    topology, registry, snapshot, clock = fixture()
    bad_sample = snapshot.memory[0].model_copy(update={"observed_used_bytes": True})
    snapshot = snapshot.model_copy(
        update={"memory": (bad_sample, *snapshot.memory[1:])}
    )
    with pytest.raises(ValidationError):
        evaluate(topology, registry, snapshot, clock)


def test_deep_immutability_and_no_input_mutation_on_success_or_refusal():
    topology, registry, snapshot, clock = fixture()
    request = request_for(topology, snapshot)
    inputs = (topology, registry, snapshot, request, clock)
    before = tuple(item.model_dump() for item in inputs)
    result = evaluate(topology, registry, snapshot, clock, request)
    for model, field in (
        (topology, "revision"),
        (topology.devices[0], "ordinal"),
        (snapshot.memory[0], "observed_used_bytes"),
        (request.demands[0], "bytes"),
        (result.proposal.budgets[0], "remaining_bytes"),
    ):
        with pytest.raises(ValidationError):
            setattr(model, field, 999)
    with pytest.raises(TypeError):
        topology.devices[0] = topology.devices[1]
    evaluate(topology, registry, snapshot, changed(clock, now_ns=2000), request)
    assert tuple(item.model_dump() for item in inputs) == before
    raw = topology.model_dump()
    rebuilt = ResourceTopology.model_validate(raw)
    raw["devices"][0]["ordinal"] = 999
    assert rebuilt == topology


def permuted(rng, values):
    values = list(values)
    rng.shuffle(values)
    return tuple(values)


def test_permutation_and_volatile_ordinal_invariance_for_fit_and_refusal():
    rng = random.Random(42017)
    topology, registry, snapshot, clock = fixture()
    request = request_for(topology, snapshot, ("a", "b", "uma"))
    for failing in (False, True):
        if failing:
            snapshot = replace_item(
                snapshot, "devices", "resource_id", "a", health="quarantined"
            )
            snapshot = replace_item(
                snapshot, "memory", "resource_id", "host", observed_at_ns=1200
            )
        expected = evaluate(topology, registry, snapshot, clock, request)
        for order in itertools.permutations(topology.devices):
            ordinals = rng.sample(range(20), 2)
            remapped = tuple(
                changed(d, ordinal=ordinals[0 if d.logical_id == "a" else 1])
                if d.backend == "cuda"
                else d
                for d in order
            )
            candidate = evaluate(
                changed(
                    topology, devices=remapped, domains=permuted(rng, topology.domains)
                ),
                changed(registry, accelerators=permuted(rng, registry.accelerators)),
                changed(
                    snapshot,
                    devices=permuted(rng, snapshot.devices),
                    memory=permuted(rng, snapshot.memory),
                ),
                clock,
                changed(
                    request,
                    devices=permuted(rng, request.devices),
                    demands=permuted(rng, request.demands),
                ),
            )
            assert candidate == expected


def test_seeded_conservation_monotonicity_and_allocation_permutation():
    rng = random.Random(20261030)
    for _ in range(160):
        topology, registry, snapshot, clock = fixture()
        reservations = [rng.randrange(0, 30) for _ in range(3)]
        attribution = [rng.randrange(0, 30) for _ in range(3)]
        external = rng.randrange(0, 30)
        system = rng.randrange(0, 30)
        peak = rng.randrange(1, 30)
        charged = external + sum(
            max(r, a) for r, a in zip(reservations, attribution, strict=True)
        )
        total = system + charged + peak
        topology = replace_item(
            topology,
            "domains",
            "domain_id",
            "vram-a",
            total_bytes=total,
            system_reserved_bytes=system,
        )
        entries = tuple(
            Commitment(
                allocation_id=f"old-{i}",
                domain_id="vram-a",
                reserved_bytes=r,
                state=state,
            )
            for i, (r, state) in enumerate(
                zip(reservations, ("pending", "active", "uncertain"), strict=True)
            )
        )
        attributed = tuple(
            Attribution(allocation_id=f"old-{i}", bytes=a)
            for i, a in enumerate(attribution)
        )
        snapshot = changed(snapshot, commitments=entries)
        snapshot = replace_item(
            snapshot,
            "memory",
            "resource_id",
            "vram-a",
            observed_used_bytes=external + sum(attribution),
            attributed=attributed,
        )
        demand = Demand(allocation_id="new", domain_id="vram-a", bytes=peak)
        request = request_for(topology, snapshot, demands=(demand,))
        result = evaluate(topology, registry, snapshot, clock, request)
        budget = result.proposal.budgets[0]
        assert budget.external_bytes == external
        assert budget.committed_bytes == charged - external
        assert budget.remaining_bytes == 0
        assert total == sum(
            (
                budget.system_reserved_bytes,
                budget.external_bytes,
                budget.committed_bytes,
                budget.requested_bytes,
                budget.remaining_bytes,
            )
        )
        shuffled = changed(snapshot, commitments=permuted(rng, entries))
        shuffled = replace_item(
            shuffled,
            "memory",
            "resource_id",
            "vram-a",
            attributed=permuted(rng, attributed),
        )
        assert evaluate(topology, registry, shuffled, clock, request) == result
        for delta in (1, rng.randrange(2, 100)):
            bigger = replace_item(
                topology, "domains", "domain_id", "vram-a", total_bytes=total + delta
            )
            assert (
                evaluate(bigger, registry, snapshot, clock, request)
                .proposal.budgets[0]
                .remaining_bytes
                == delta
            )
            bigger_demand = changed(
                request, demands=(changed(demand, bytes=peak + delta),)
            )
            assert_refused(
                evaluate(topology, registry, snapshot, clock, bigger_demand),
                RefusalCode.INSUFFICIENT_CAPACITY,
            )
        if peak > 1:
            smaller_demand = changed(
                request, demands=(changed(demand, bytes=peak - 1),)
            )
            assert (
                evaluate(topology, registry, snapshot, clock, smaller_demand)
                .proposal.budgets[0]
                .remaining_bytes
                == 1
            )
        smaller_capacity = replace_item(
            topology, "domains", "domain_id", "vram-a", total_bytes=total - 1
        )
        assert_refused(
            evaluate(smaller_capacity, registry, snapshot, clock, request),
            RefusalCode.INSUFFICIENT_CAPACITY,
        )


def test_import_bodies_and_assessment_do_not_perform_io_or_sample_time(monkeypatch):
    # Read/compile source before guarding. Dependencies are already loaded;
    # the guard covers fresh module-body execution, not Python's source loader.
    modules = (topology_module, accounting)
    compiled = tuple(
        (module, compile(Path(module.__file__).read_text(), module.__file__, "exec"))
        for module in modules
    )
    topology, registry, snapshot, clock = fixture()

    def forbidden(*args, **kwargs):
        raise AssertionError("P1 attempted I/O, process creation, or clock sampling")

    with monkeypatch.context() as guard:
        for owner, names in (
            (builtins, ("open",)),
            (io, ("open",)),
            (os, ("open", "stat", "listdir", "scandir", "system")),
            (socket, ("socket", "create_connection")),
            (subprocess, ("Popen", "run")),
            (
                time,
                (
                    "time",
                    "time_ns",
                    "monotonic",
                    "monotonic_ns",
                    "perf_counter",
                    "sleep",
                ),
            ),
        ):
            for name in names:
                guard.setattr(owner, name, forbidden)
        for module, code in compiled:
            namespace = {"__name__": module.__name__, "__package__": module.__package__}
            exec(code, namespace)
        assert evaluate(topology, registry, snapshot, clock).fits
