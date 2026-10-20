"""Stateless execution hooks; ownership stays with the Gateway scheduler/leases.

These checks describe legacy runtime occupancy, never physical GPU reuse safety.
Only server-owned provider bindings may select an adapter.
"""
from types import MappingProxyType
from typing import Protocol

from .residency import GPUResidency, ResidencyError


class EngineLifecycleError(ResidencyError):
    pass


class EngineLifecycle(Protocol):
    async def prepare(self, residency: GPUResidency | None) -> None: ...
    def verify_active(self, residency: GPUResidency | None) -> bool: ...
    async def release(self, residency: GPUResidency | None) -> None: ...


class OllamaLifecycle:
    __slots__ = ()

    async def prepare(self, residency):
        if not self.verify_active(residency):
            raise EngineLifecycleError("Ollama requires legacy LLM residency")

    def verify_active(self, residency):
        # None preserves standalone lease-registry users without residency.
        return residency is None or residency.state == "llm"

    async def release(self, residency):
        # Scheduled HTTP owns dispatch and completion; no unload or safety claim.
        pass


class ComfyUILifecycle:
    __slots__ = ()

    async def prepare(self, residency):
        if residency is not None:
            await residency.enter_media()

    def verify_active(self, residency):
        return residency is None or residency.state == "media"

    async def release(self, residency):
        if residency is not None:
            await residency.leave_media()


_ADAPTERS = MappingProxyType({
    "ollama-local": OllamaLifecycle(),
    "comfyui-local": ComfyUILifecycle(),
})
# External execution is a separate, explicit permission, not adapter discovery.
_EXTERNAL_PROVIDERS = frozenset({"comfyui-local"})


def lifecycle_for(provider: str, *, external: bool = False) -> EngineLifecycle:
    if provider == "vision-local":
        raise EngineLifecycleError("DENIED_UNAVAILABLE: vision-local")
    if provider not in _ADAPTERS or (external and provider not in _EXTERNAL_PROVIDERS):
        raise EngineLifecycleError("execution adapter unavailable for this path")
    return _ADAPTERS[provider]
