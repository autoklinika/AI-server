"""DEV on-demand ComfyUI engine on the existing Resource Manager lease.

The controller must be independently trusted; no shell/service mutation
is provided or activated by this module. Production defaults are unchanged.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import uuid
from typing import Protocol

from .residency import GPUResidency, ResidencyError


class OnDemandComfyError(ResidencyError):
    pass


@dataclass(frozen=True)
class ServiceIdentity:
    boot_id: str
    incarnation: str
    pid: int
    cgroup: str
    process_start_ticks: int


class ManagedComfyController(Protocol):
    async def start(self) -> ServiceIdentity: ...
    def running(self, identity: ServiceIdentity) -> bool: ...
    async def stop_and_verify(self, identity: ServiceIdentity) -> None: ...


class UnapprovedController:
    """Fail-closed: merely enabling a DEV flag cannot start a GPU process."""
    async def start(self) -> ServiceIdentity:
        raise OnDemandComfyError("trusted service controller NOT_ADMITTED")

    def running(self, identity: ServiceIdentity) -> bool:
        return False

    async def stop_and_verify(self, identity: ServiceIdentity) -> None:
        raise OnDemandComfyError("trusted service controller NOT_ADMITTED")


class OnDemandComfyLifecycle:
    """One lease: dirty -> start -> ready -> media -> free -> stop -> release."""

    def __init__(self, controller: ManagedComfyController):
        self.controller=controller
        self.identity: ServiceIdentity | None=None

    async def prepare(self, residency: GPUResidency | None) -> None:
        if residency is None or residency.state!="llm" or self.identity is not None:
            raise OnDemandComfyError("ComfyUI start not allowed in current RM state")
        try:
            # A durable recovery marker must precede opening any GPU device.
            residency._dirty()
            # Ollama/Qwen must be unloaded BEFORE managed ComfyUI opens KFD.
            # The lease and recovery fence remain held throughout both phases.
            await residency.drain_ollama_before_managed_comfy_start()
            identity=await self.controller.start()
            if not isinstance(identity,ServiceIdentity):
                raise OnDemandComfyError("invalid managed service identity")
            if (type(identity.pid) is not int or identity.pid<=1 or
                type(identity.process_start_ticks) is not int or
                identity.process_start_ticks<=0 or
                identity.cgroup!="/system.slice/ai-rm-comfy-ondemand-dev.service" or
                not isinstance(identity.incarnation,str) or
                not re.fullmatch(r"[0-9a-f]{32}",identity.incarnation)):
                raise OnDemandComfyError("untrusted managed process/cgroup incarnation")
            try:
                boot=str(uuid.UUID(identity.boot_id))
                if boot!=Path("/proc/sys/kernel/random/boot_id").read_text().strip():
                    raise OnDemandComfyError("service started in different boot")
            except (ValueError,AttributeError,OSError) as exc:
                raise OnDemandComfyError("managed service boot ID unavailable") from exc
            self.identity=identity
            if not self.controller.running(identity):
                raise OnDemandComfyError("service not running with pinned identity")
            await residency.enter_media()
            if not self.verify_active(residency):
                raise OnDemandComfyError("service incarnation drift after admission")
        except BaseException as exc:
            residency.state="blocked"
            if isinstance(exc, Exception) and not isinstance(exc, ResidencyError):
                raise OnDemandComfyError("managed ComfyUI process transition failed") from exc
            raise

    def verify_active(self, residency: GPUResidency | None) -> bool:
        return bool(residency is not None and residency.state=="media"
                    and self.identity is not None
                    and self.identity.boot_id ==
                        Path("/proc/sys/kernel/random/boot_id").read_text().strip()
                    and self.controller.running(self.identity))

    async def release(self, residency: GPUResidency | None) -> None:
        if residency is None or not self.verify_active(residency):
            raise OnDemandComfyError("service ownership uncertain: refuse release")
        try:
            # No marker clearance until the entire managed process is stopped.
            await residency.leave_media(hold_until_service_stop=True)
            await self.controller.stop_and_verify(self.identity)
            residency.finalize_after_service_stop()
            self.identity=None
        except BaseException as exc:
            residency.state="blocked"
            if isinstance(exc, Exception) and not isinstance(exc, ResidencyError):
                raise OnDemandComfyError("managed ComfyUI process transition failed") from exc
            raise
