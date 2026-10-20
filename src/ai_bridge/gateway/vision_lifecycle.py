"""Lease-bound Vision lifecycle. No GPU authority is created by registration.

The executor is a trusted, in-process dependency, never an HTTP/config value.
No real GPU executor is admitted yet. CPU contract executors belong in tests.
"""
from __future__ import annotations

from dataclasses import dataclass
import asyncio
import math
import re
from typing import Callable, Protocol

from .engine_lifecycle import EngineLifecycleError


@dataclass(frozen=True)
class VisionOwner:
    lease_id: str
    use_id: str
    job_id: int


@dataclass(frozen=True)
class VisionSession:
    generation: str
    worker_id: str
    resource_id: str

    def valid(self):
        return (all(type(v) is str and 0 < len(v) <= 128 for v in
                    (self.generation, self.worker_id, self.resource_id))
                and self.resource_id == "local-primary")


@dataclass(frozen=True)
class VisionCleanup:
    owner: VisionOwner
    session: VisionSession
    job_terminal: bool
    model_unloaded: bool
    execution_closed: bool
    # Supplied by the trusted supervisor, NEVER inferred from worker output,
    # empty queues, process exit or torch.cuda.empty_cache().
    release_authorized: bool


class VisionExecutor(Protocol):
    """A future admitted executor must implement the existing safety boundary.

    available() must stay false without an authorized launch AND cleanup path.
    verify() must check the same worker incarnation, owner and resource.
    inspect() accepts an opaque server-registered image ID, never a command/path.
    cleanup() must account for the full execution, including descendants.
    """
    resource_id: str
    def available(self) -> bool: ...
    async def prepare(self, owner: VisionOwner) -> VisionSession: ...
    def verify(self, owner: VisionOwner, session: VisionSession) -> bool: ...
    async def inspect(self, owner: VisionOwner, session: VisionSession, image_id: str) -> dict: ...
    async def cleanup(self, owner: VisionOwner, session: VisionSession) -> VisionCleanup: ...


class VisionLifecycleAdapter:
    """One use of one existing RM lease; no scheduler and no external grant API."""

    def __init__(self, executor: VisionExecutor, owner: VisionOwner,
                 owns_lease: Callable[[], bool], *, timeout: float = 90):
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("invalid Vision timeout")
        self.executor, self.owner = executor, owner
        self.owns_lease, self.timeout = owns_lease, timeout
        self.session = None
        self.executing = False
        self.completed = False
        self.released = False
        self.phase = "prepare"

    def _require_owner(self):
        if not self.owns_lease() or self.released:
            raise EngineLifecycleError("Vision owner is stale or unavailable")

    async def prepare(self, residency):
        self._require_owner()
        if (self.session is not None or self.executor.resource_id != "local-primary"
                or self.executor.available() is not True):
            raise EngineLifecycleError("Vision executor not admitted for local-primary")
        if residency is None:
            raise EngineLifecycleError("Vision requires the existing GPUResidency")
        # Legacy runtime draining is not evidence of GPU_REUSE_SAFE. The trusted
        # executor must independently deny launch without its required authority.
        async with asyncio.timeout(self.timeout):
            await residency.enter_media()
            self._require_owner()
            session = await self.executor.prepare(self.owner)
            if type(session) is not VisionSession or not session.valid():
                raise EngineLifecycleError("Vision executor session invalid")
            self.session = session
            if not self.verify_active(residency):
                raise EngineLifecycleError("Vision executor is not ready")
        self.phase = "execute"

    def verify_active(self, residency):
        self._require_owner()
        return (self.session is not None and residency is not None
                and residency.state == "media"
                and self.executor.verify(self.owner, self.session) is True)

    async def execute(self, residency, image_id: str):
        if not valid_image_id(image_id):
            raise ValueError("invalid registered image ID")
        if self.executing or self.completed or not self.verify_active(residency):
            raise EngineLifecycleError("Vision execution is not available")
        # Publish before awaiting: two HTTP requests can never execute this use.
        self.executing = True
        try:
            async with asyncio.timeout(self.timeout):
                result = await self.executor.inspect(self.owner, self.session, image_id)
                if (not self.verify_active(residency) or not isinstance(result, dict)
                        or result.get("image_id") != image_id):
                    raise EngineLifecycleError("Vision result/worker identity mismatch")
            self.completed = True
            return result
        finally:
            self.executing = False

    async def release(self, residency):
        self._require_owner()
        if self.executing or not self.completed or not self.verify_active(residency):
            raise EngineLifecycleError("Vision execution/cleanup not verified")
        self.phase = "release"
        async with asyncio.timeout(self.timeout):
            evidence = await self.executor.cleanup(self.owner, self.session)
            if (type(evidence) is not VisionCleanup
                    or evidence.owner != self.owner or evidence.session != self.session
                    or not all(value is True for value in (
                        evidence.job_terminal, evidence.model_unloaded,
                        evidence.execution_closed, evidence.release_authorized))):
                raise EngineLifecycleError("Vision cleanup not authorized")
            self._require_owner()
            await residency.leave_media()
        self.released = True


def valid_image_id(value):
    return type(value) is str and re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,95}", value) is not None
