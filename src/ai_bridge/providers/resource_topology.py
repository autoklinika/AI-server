"""P1 declarations only: no discovery, hardware proof or execution authority."""

from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .accelerators import AcceleratorRegistry

Identifier = Annotated[str, Field(min_length=1, max_length=256, pattern=r"^\S+$")]
Bytes = Annotated[int, Field(ge=0)]
PositiveBytes = Annotated[int, Field(gt=0)]
Generation = Annotated[int, Field(ge=0)]
Backend = Literal["cuda", "rocm", "vulkan"]


class InputCode(StrEnum):
    DUPLICATE = "duplicate"
    REFERENCE = "reference"
    BINDING = "binding"
    INVENTORY = "inventory"
    ATTRIBUTION = "attribution"
    REUSED_ALLOCATION = "reused_allocation"


class ResourceInputError(ValueError):
    """Well-typed but inconsistent declarations; never a fit result."""

    def __init__(self, code: InputCode, resource: str):
        self.code = code
        self.resource = resource
        super().__init__(f"{code.value}: {resource}")


class FrozenModel(BaseModel):
    model_config = ConfigDict(
        frozen=True,
        strict=True,
        extra="forbid",
        validate_default=True,
        revalidate_instances="always",
        hide_input_in_errors=True,
    )


def index_unique[T: BaseModel](items: tuple[T, ...], field: str) -> dict[str, T]:
    """Build a local index; duplicate diagnostics are independent of input order."""
    result: dict[str, T] = {}
    for item in sorted(items, key=lambda value: getattr(value, field)):
        key = getattr(item, field)
        if key in result:
            raise ResourceInputError(InputCode.DUPLICATE, key)
        result[key] = item
    return result


class FaultDomain(FrozenModel):
    fault_domain_id: Identifier
    generation: Generation


class MemoryDomain(FrozenModel):
    domain_id: Identifier
    node_id: Identifier
    kind: Literal["host", "dedicated"]
    generation: Generation
    total_bytes: PositiveBytes | None
    system_reserved_bytes: Bytes
    fault_domain_id: Identifier | None = None

    @model_validator(mode="after")
    def headroom_fits(self) -> Self:
        if (
            self.total_bytes is not None
            and self.system_reserved_bytes > self.total_bytes
        ):
            raise ValueError("system headroom exceeds total capacity")
        return self


class Device(FrozenModel):
    logical_id: Identifier
    physical_id: Identifier
    generation: Generation
    node_id: Identifier
    backend: Backend
    runtime_id: Identifier
    ordinal: Generation
    memory_class: Literal["unified", "dedicated"]
    memory_domain_id: Identifier
    fault_domain_id: Identifier | None = None


class ResourceTopology(FrozenModel):
    revision: Generation
    devices: tuple[Device, ...]
    domains: tuple[MemoryDomain, ...]
    fault_domains: tuple[FaultDomain, ...] = ()

    def validate_against(self, registry: AcceleratorRegistry) -> None:
        """Mandatory assessment boundary; N0 itself remains unchanged."""
        topology = ResourceTopology.model_validate(self)
        if type(registry) is not AcceleratorRegistry:
            raise TypeError("registry must be an AcceleratorRegistry")
        inventory = AcceleratorRegistry.model_validate(
            registry.model_dump(), strict=True
        )
        devices = index_unique(topology.devices, "logical_id")
        index_unique(topology.devices, "physical_id")
        domains = index_unique(topology.domains, "domain_id")
        faults = index_unique(topology.fault_domains, "fault_domain_id")
        descriptors = index_unique(inventory.accelerators, "accelerator_id")
        node_ids = {item.node_id for item in inventory.accelerators}
        # Host RAM is shared by CPU and UMA users, including devices omitted
        # from this partial topology. Disabling a descriptor does not enlarge
        # the physical memory pool. Dedicated VRAM never bounds host RAM.
        host_limits: dict[str, int] = {}
        for inventory_descriptor in descriptors.values():
            known_total = inventory_descriptor.total_memory_bytes
            if (
                inventory_descriptor.memory_class in ("unified", "host")
                and known_total is not None
            ):
                node_id = inventory_descriptor.node_id
                host_limits[node_id] = min(
                    host_limits.get(node_id, known_total), known_total
                )
        ordinals: set[tuple[str, str, int]] = set()
        runtimes: dict[tuple[str, str], str] = {}
        dedicated: set[str] = set()
        hosts: set[str] = set()
        for domain in domains.values():
            if domain.node_id not in node_ids or (
                domain.fault_domain_id is not None
                and domain.fault_domain_id not in faults
            ):
                raise ResourceInputError(InputCode.REFERENCE, domain.domain_id)
            if domain.kind == "host":
                known_host_limit = host_limits.get(domain.node_id)
                if (
                    known_host_limit is not None
                    and domain.total_bytes is not None
                    and domain.total_bytes > known_host_limit
                ):
                    raise ResourceInputError(InputCode.INVENTORY, domain.domain_id)
                if domain.node_id in hosts:
                    raise ResourceInputError(InputCode.BINDING, domain.domain_id)
                hosts.add(domain.node_id)
        for device in devices.values():
            bound_domain = domains.get(device.memory_domain_id)
            descriptor = descriptors.get(device.logical_id)
            if bound_domain is None or (
                device.fault_domain_id is not None
                and device.fault_domain_id not in faults
            ):
                raise ResourceInputError(InputCode.REFERENCE, device.logical_id)
            expected_kind = "host" if device.memory_class == "unified" else "dedicated"
            if (
                bound_domain.node_id != device.node_id
                or bound_domain.kind != expected_kind
            ):
                raise ResourceInputError(InputCode.BINDING, device.logical_id)
            if bound_domain.kind == "dedicated":
                if bound_domain.domain_id in dedicated:
                    raise ResourceInputError(InputCode.BINDING, device.logical_id)
                dedicated.add(bound_domain.domain_id)
            runtime = (device.node_id, device.runtime_id)
            ordinal = (*runtime, device.ordinal)
            if ordinal in ordinals:
                raise ResourceInputError(InputCode.DUPLICATE, device.logical_id)
            if runtime in runtimes and runtimes[runtime] != device.backend:
                raise ResourceInputError(InputCode.BINDING, device.logical_id)
            ordinals.add(ordinal)
            runtimes[runtime] = device.backend
            if (
                descriptor is None
                or not descriptor.enabled
                or (descriptor.node_id, descriptor.backend, descriptor.memory_class)
                != (device.node_id, device.backend, device.memory_class)
                or (
                    descriptor.total_memory_bytes is not None
                    and bound_domain.total_bytes is not None
                    and bound_domain.total_bytes > descriptor.total_memory_bytes
                )
            ):
                raise ResourceInputError(InputCode.INVENTORY, device.logical_id)
        for domain in domains.values():
            if domain.kind == "dedicated" and domain.domain_id not in dedicated:
                raise ResourceInputError(InputCode.BINDING, domain.domain_id)
