"""Stage N0 static accelerator inventory and routing constraints.

Inventory is configuration, not live health. No driver probing or hardware
selection occurs here. Existing provider and scheduler contracts remain
authoritative until a later hardware activation stage.
"""
from __future__ import annotations

from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .registry import DescriptorId, DescriptorRegistry


AcceleratorKind = Literal["integrated", "discrete", "virtual"]
AcceleratorBackend = Literal["rocm", "cuda", "vulkan", "cpu", "unknown"]
MemoryClass = Literal["unified", "dedicated", "host"]
Locality = Literal["local", "remote"]


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)


class AcceleratorDescriptor(_Model):
    accelerator_id: DescriptorId
    node_id: DescriptorId
    kind: AcceleratorKind
    backend: AcceleratorBackend
    memory_class: MemoryClass
    locality: Locality = "local"
    total_memory_bytes: int | None = Field(default=None, strict=True, gt=0)
    workload_classes: tuple[DescriptorId, ...] = Field(min_length=1)
    enabled: bool = True

    @model_validator(mode="after")
    def validate_workload_classes(self) -> Self:
        if len(set(self.workload_classes)) != len(self.workload_classes):
            raise ValueError("duplicate accelerator workload class")
        return self


class ProviderAcceleratorBinding(_Model):
    provider_id: DescriptorId
    accelerator_ids: tuple[DescriptorId, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_accelerators(self) -> Self:
        if len(set(self.accelerator_ids)) != len(self.accelerator_ids):
            raise ValueError("duplicate provider accelerator binding")
        return self


class AcceleratorRequirements(_Model):
    backends: tuple[AcceleratorBackend, ...] = ()
    memory_classes: tuple[MemoryClass, ...] = ()
    min_memory_bytes: int | None = Field(default=None, strict=True, gt=0)
    locality: Locality | None = None

    @model_validator(mode="after")
    def unique_constraints(self) -> Self:
        if len(set(self.backends)) != len(self.backends):
            raise ValueError("duplicate accelerator backend requirement")
        if len(set(self.memory_classes)) != len(self.memory_classes):
            raise ValueError("duplicate accelerator memory-class requirement")
        return self


class AcceleratorRegistry(_Model):
    schema_version: int = Field(default=1, strict=True, ge=1, le=1)
    accelerators: tuple[AcceleratorDescriptor, ...] = Field(min_length=1)
    provider_bindings: tuple[ProviderAcceleratorBinding, ...] = ()

    @model_validator(mode="after")
    def unique_ids(self) -> Self:
        ids = [item.accelerator_id for item in self.accelerators]
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate accelerator identifier")
        providers = [item.provider_id for item in self.provider_bindings]
        if len(set(providers)) != len(providers):
            raise ValueError("duplicate provider accelerator binding")
        return self

    def accelerator(self, accelerator_id: str) -> AcceleratorDescriptor:
        for item in self.accelerators:
            if item.accelerator_id == accelerator_id:
                return item
        raise ValueError("unknown accelerator descriptor")

    def validate_references(self, providers: DescriptorRegistry) -> None:
        node_ids = {node.node_id for node in providers.nodes}
        for item in self.accelerators:
            if item.node_id not in node_ids:
                raise ValueError("accelerator node mismatch")
        for binding in self.provider_bindings:
            providers.provider(binding.provider_id)
            for accelerator_id in binding.accelerator_ids:
                self.accelerator(accelerator_id)
    def candidates(
        self,
        provider_id: str,
        requirements: AcceleratorRequirements | None = None,
    ) -> tuple[AcceleratorDescriptor, ...]:
        req = requirements or AcceleratorRequirements()
        binding = next(
            (item for item in self.provider_bindings if item.provider_id == provider_id),
            None,
        )
        if binding is None:
            return ()
        result = []
        for accelerator_id in binding.accelerator_ids:
            item = self.accelerator(accelerator_id)
            if not item.enabled:
                continue
            if req.backends and item.backend not in req.backends:
                continue
            if req.memory_classes and item.memory_class not in req.memory_classes:
                continue
            if req.locality is not None and item.locality != req.locality:
                continue
            if req.min_memory_bytes is not None:
                if item.total_memory_bytes is None or item.total_memory_bytes < req.min_memory_bytes:
                    continue
            result.append(item)
        return tuple(result)

    def snapshot(self) -> dict[str, object]:
        return self.model_dump(mode="json")


def accelerator_state_snapshot(
    registry: AcceleratorRegistry,
    primary_residency: dict[str, object],
    *,
    primary_accelerator_id: str = "local-primary",
) -> dict[str, object]:
    devices = []
    for item in registry.accelerators:
        row = item.model_dump(mode="json")
        row["residency"] = (
            dict(primary_residency)
            if item.accelerator_id == primary_accelerator_id
            else {
                "state": "unmanaged",
                "recovery_required": False,
                "cleanup_evidence": None,
            }
        )
        devices.append(row)
    return {
        "schema_version": registry.schema_version,
        "primary_accelerator_id": primary_accelerator_id,
        "devices": devices,
        "provider_bindings": [
            item.model_dump(mode="json") for item in registry.provider_bindings
        ],
    }


def local_accelerator_registry(node_id: str = "ai-node-01") -> AcceleratorRegistry:
    """N0 baseline: describe today's single shared local accelerator explicitly."""
    return AcceleratorRegistry(
        accelerators=(AcceleratorDescriptor(
            accelerator_id="local-primary",
            node_id=node_id,
            kind="integrated",
            backend="unknown",
            memory_class="unified",
            workload_classes=("llm", "media-generation"),
        ),),
        provider_bindings=(
            ProviderAcceleratorBinding(
                provider_id="ollama-local",
                accelerator_ids=("local-primary",),
            ),
            ProviderAcceleratorBinding(
                provider_id="comfyui-local",
                accelerator_ids=("local-primary",),
            ),
        ),
    )
