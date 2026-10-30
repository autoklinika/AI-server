"""Pure, conditional P1 fit assessment. The existing RM alone may commit in P2."""

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field

from ai_bridge.providers.accelerators import AcceleratorRegistry
from ai_bridge.providers.resource_topology import (
    Backend,
    Bytes,
    FrozenModel,
    Generation,
    Identifier,
    InputCode,
    PositiveBytes,
    ResourceInputError,
    ResourceTopology,
    index_unique,
)


class RefusalCode(StrEnum):
    REVISION = "revision"
    CLOCK_EPOCH = "clock_epoch"
    DEVICE_MISMATCH = "device_mismatch"
    MISSING_TELEMETRY = "missing_telemetry"
    GENERATION = "generation"
    UNHEALTHY = "unhealthy"
    STALE = "stale"
    FUTURE = "future"
    MISSING_CAPACITY = "missing_capacity"
    INSUFFICIENT_CAPACITY = "insufficient_capacity"


class AssessmentClock(FrozenModel):
    epoch: Identifier
    now_ns: Generation
    max_age_ns: Generation


class Observation(FrozenModel):
    resource_id: Identifier
    generation: Generation
    epoch: Identifier
    observed_at_ns: Generation
    health: Literal["healthy", "busy", "unavailable", "quarantined", "unknown"]


class Attribution(FrozenModel):
    allocation_id: Identifier
    bytes: Bytes


class MemoryObservation(Observation):
    observed_used_bytes: Bytes | None
    attributed: tuple[Attribution, ...]


class Allocation(FrozenModel):
    allocation_id: Identifier
    domain_id: Identifier


class Commitment(Allocation):
    reserved_bytes: Bytes
    state: Literal["pending", "active", "uncertain"]


class ResourceSnapshot(FrozenModel):
    revision: Generation
    topology_revision: Generation
    epoch: Identifier
    devices: tuple[Observation, ...]
    memory: tuple[MemoryObservation, ...]
    faults: tuple[Observation, ...]
    commitments: tuple[Commitment, ...]


class DeviceRequest(FrozenModel):
    logical_id: Identifier
    physical_id: Identifier
    generation: Generation
    backend: Backend
    runtime_id: Identifier


class Demand(Allocation):
    bytes: PositiveBytes


class ResourceRequest(FrozenModel):
    node_id: Identifier
    expected_revision: Generation
    topology_revision: Generation
    epoch: Identifier
    devices: tuple[DeviceRequest, ...]
    demands: Annotated[tuple[Demand, ...], Field(min_length=1)]


class Diagnostic(FrozenModel):
    code: RefusalCode
    # References add a prefix to an already validated, at-most-256-character ID.
    resource_id: Annotated[str, Field(min_length=1, max_length=512, pattern=r"^\S+$")]


class DomainBudget(FrozenModel):
    domain_id: Identifier
    total_bytes: PositiveBytes
    system_reserved_bytes: Bytes
    external_bytes: Bytes
    committed_bytes: Bytes
    requested_bytes: PositiveBytes
    remaining_bytes: Bytes


class NonAuthorizing(FrozenModel):
    @property
    def authorizes_execution(self) -> Literal[False]:
        return False

    def __bool__(self) -> bool:
        raise TypeError(
            "P1 is not execution authority; inspect fits/proposal explicitly"
        )


class FitProposal(NonAuthorizing):
    request: ResourceRequest
    clock: AssessmentClock
    budgets: tuple[DomainBudget, ...]


class FitAssessment(NonAuthorizing):
    proposal: FitProposal | None
    diagnostics: tuple[Diagnostic, ...]

    @property
    def fits(self) -> bool:
        return self.proposal is not None


def _index_allocations[A: Allocation](
    entries: tuple[A, ...], domain_ids: set[str]
) -> dict[tuple[str, str], A]:
    result: dict[tuple[str, str], A] = {}
    for entry in sorted(entries, key=lambda item: (item.domain_id, item.allocation_id)):
        key = (entry.domain_id, entry.allocation_id)
        if entry.domain_id not in domain_ids:
            raise ResourceInputError(InputCode.REFERENCE, entry.domain_id)
        if key in result:
            raise ResourceInputError(InputCode.DUPLICATE, "/".join(key))
        result[key] = entry
    return result


def assess_fit(
    topology: ResourceTopology,
    registry: AcceleratorRegistry,
    snapshot: ResourceSnapshot,
    request: ResourceRequest,
    clock: AssessmentClock,
) -> FitAssessment:
    """Validate all declarations; return a whole-bundle proposal or explicit refusal.

    Type/shape errors raise ValidationError; inconsistent input raises
    ResourceInputError. No invalid input is converted into an empty/free snapshot.
    """
    topology = ResourceTopology.model_validate(topology)
    snapshot = ResourceSnapshot.model_validate(snapshot)
    request = ResourceRequest.model_validate(request)
    clock = AssessmentClock.model_validate(clock)
    topology.validate_against(registry)
    devices = index_unique(topology.devices, "logical_id")
    domains = index_unique(topology.domains, "domain_id")
    faults = index_unique(topology.fault_domains, "fault_domain_id")
    selected = index_unique(request.devices, "logical_id")
    device_samples = index_unique(snapshot.devices, "resource_id")
    memory_samples = index_unique(snapshot.memory, "resource_id")
    fault_samples = index_unique(snapshot.faults, "resource_id")
    for samples, resources in (
        (device_samples, devices),
        (memory_samples, domains),
        (fault_samples, faults),
        (selected, devices),
    ):
        unknown = sorted(set(samples) - set(resources))
        if unknown:
            raise ResourceInputError(InputCode.REFERENCE, unknown[0])

    # Canonical per-domain allocation keys; even identical repeats are ambiguous.
    commitments = _index_allocations(snapshot.commitments, set(domains))
    demands = _index_allocations(request.demands, set(domains))
    reused = sorted(set(commitments) & set(demands))
    if reused:
        raise ResourceInputError(InputCode.REUSED_ALLOCATION, "/".join(reused[0]))
    attributed: dict[tuple[str, str], int] = {}
    for domain_id, observed_sample in memory_samples.items():
        allocations = index_unique(observed_sample.attributed, "allocation_id")
        for allocation_id, attribution in allocations.items():
            key = (domain_id, allocation_id)
            if key not in commitments:
                raise ResourceInputError(InputCode.ATTRIBUTION, "/".join(key))
            attributed[key] = attribution.bytes
        observed = observed_sample.observed_used_bytes
        total = domains[domain_id].total_bytes
        if (observed is None and allocations) or (
            observed is not None
            and (
                sum(item.bytes for item in allocations.values()) > observed
                or (total is not None and observed > total)
            )
        ):
            raise ResourceInputError(InputCode.ATTRIBUTION, domain_id)

    requested_domains = {entry.domain_id for entry in request.demands}
    bound_domains = {devices[key].memory_domain_id for key in selected}
    for domain_id in sorted(requested_domains):
        domain = domains[domain_id]
        if domain.node_id != request.node_id or (
            domain.kind == "dedicated" and domain_id not in bound_domains
        ):
            raise ResourceInputError(InputCode.BINDING, domain_id)
    for logical_id in sorted(selected):
        if devices[logical_id].memory_domain_id not in requested_domains:
            raise ResourceInputError(InputCode.BINDING, logical_id)

    failures: set[tuple[RefusalCode, str]] = set()
    if (
        snapshot.revision != request.expected_revision
        or snapshot.topology_revision != topology.revision
        or request.topology_revision != topology.revision
    ):
        failures.add((RefusalCode.REVISION, "snapshot"))
    if snapshot.epoch != clock.epoch or request.epoch != clock.epoch:
        failures.add((RefusalCode.CLOCK_EPOCH, "snapshot"))
    for logical_id, wanted in selected.items():
        current = devices[logical_id]
        if wanted.generation != current.generation:
            failures.add((RefusalCode.GENERATION, f"device:{logical_id}"))
        if current.node_id != request.node_id or (
            wanted.physical_id,
            wanted.backend,
            wanted.runtime_id,
        ) != (current.physical_id, current.backend, current.runtime_id):
            failures.add((RefusalCode.DEVICE_MISMATCH, f"device:{logical_id}"))

    selected_devices = tuple(devices[device_id] for device_id in selected)
    selected_memory = tuple(
        domains[domain_id] for domain_id in sorted(requested_domains)
    )
    required_faults = {
        device.fault_domain_id
        for device in selected_devices
        if device.fault_domain_id is not None
    } | {
        domain.fault_domain_id
        for domain in selected_memory
        if domain.fault_domain_id is not None
    }
    required_devices = set(selected) | {
        key for key, item in devices.items() if item.fault_domain_id in required_faults
    }
    required_memory = requested_domains | {
        key for key, item in domains.items() if item.fault_domain_id in required_faults
    }

    def check(sample: Observation | None, generation: int, resource: str) -> None:
        if sample is None:
            failures.add((RefusalCode.MISSING_TELEMETRY, resource))
            return
        if sample.generation != generation:
            failures.add((RefusalCode.GENERATION, resource))
        if sample.epoch != clock.epoch:
            failures.add((RefusalCode.CLOCK_EPOCH, resource))
        if sample.health != "healthy":
            failures.add((RefusalCode.UNHEALTHY, resource))
        if sample.observed_at_ns > clock.now_ns:
            failures.add((RefusalCode.FUTURE, resource))
        elif clock.now_ns - sample.observed_at_ns > clock.max_age_ns:
            failures.add((RefusalCode.STALE, resource))

    for device_id in sorted(required_devices):
        check(
            device_samples.get(device_id),
            devices[device_id].generation,
            f"device:{device_id}",
        )
    for memory_id in sorted(required_memory):
        required_sample = memory_samples.get(memory_id)
        check(required_sample, domains[memory_id].generation, f"memory:{memory_id}")
        if domains[memory_id].total_bytes is None:
            failures.add((RefusalCode.MISSING_CAPACITY, f"memory:{memory_id}"))
        if required_sample is None or required_sample.observed_used_bytes is None:
            failures.add((RefusalCode.MISSING_TELEMETRY, f"memory:{memory_id}"))
    for fault_id in sorted(required_faults):
        check(
            fault_samples.get(fault_id),
            faults[fault_id].generation,
            f"fault:{fault_id}",
        )

    budgets: list[DomainBudget] = []
    for domain_id in sorted(requested_domains):
        domain = domains[domain_id]
        sample = memory_samples.get(domain_id)
        total = domain.total_bytes
        if sample is None or sample.observed_used_bytes is None or total is None:
            continue
        external = sample.observed_used_bytes - sum(
            value for (key, _), value in attributed.items() if key == domain_id
        )
        committed = sum(
            max(item.reserved_bytes, attributed.get(key, 0))
            for key, item in commitments.items()
            if key[0] == domain_id
        )
        requested = sum(
            item.bytes for item in request.demands if item.domain_id == domain_id
        )
        remaining = (
            total - domain.system_reserved_bytes - external - committed - requested
        )
        if remaining < 0:
            failures.add((RefusalCode.INSUFFICIENT_CAPACITY, f"memory:{domain_id}"))
        else:
            budgets.append(
                DomainBudget(
                    domain_id=domain_id,
                    total_bytes=total,
                    system_reserved_bytes=domain.system_reserved_bytes,
                    external_bytes=external,
                    committed_bytes=committed,
                    requested_bytes=requested,
                    remaining_bytes=remaining,
                )
            )
    diagnostics = tuple(
        Diagnostic(code=code, resource_id=resource)
        for code, resource in sorted(failures)
    )
    if diagnostics:
        return FitAssessment(proposal=None, diagnostics=diagnostics)
    canonical = ResourceRequest(
        node_id=request.node_id,
        expected_revision=request.expected_revision,
        topology_revision=request.topology_revision,
        epoch=request.epoch,
        devices=tuple(selected.values()),
        demands=tuple(demands.values()),
    )
    return FitAssessment(
        proposal=FitProposal(request=canonical, clock=clock, budgets=tuple(budgets)),
        diagnostics=(),
    )
