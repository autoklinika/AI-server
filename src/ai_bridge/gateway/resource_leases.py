from __future__ import annotations
import asyncio, secrets
from dataclasses import asdict, dataclass, replace
from time import monotonic
from .admission import WorkloadBinding, external_workload
from .engine_lifecycle import EngineLifecycleError, lifecycle_for
from .vision_lifecycle import VisionLifecycleAdapter, VisionOwner, valid_image_id
from .jobs import JobLifecycle, JobMetadata
from .scheduler import PriorityScheduler, SchedulerTicket

class ResourceLeaseError(RuntimeError): pass
class ResourceLeaseNotFound(ResourceLeaseError): pass
class ResourceLeaseNotActive(ResourceLeaseError): pass
class ResourceLeaseNotAllowed(ResourceLeaseError): pass

@dataclass
class _Lease:
    lease_id:str
    job_id:int
    priority:int
    source:str
    created_at:float
    last_heartbeat:float
    in_use:int=0
    release_when_idle:bool=False
    external_use_id: str | None = None
    ended_use_id: str | None = None
    external_workload: WorkloadBinding | None = None
    lifecycle: object | None = None

class ResourceLeaseRegistry:
    def __init__(self,scheduler:PriorityScheduler,*,ttl_seconds:float=45.0, residency=None, vision_executor=None, comfy_lifecycle_factory=None)->None:
        if ttl_seconds<=0: raise ValueError("ttl_seconds must be > 0")
        self.residency = residency
        self.vision_executor = vision_executor
        self.comfy_lifecycle_factory = comfy_lifecycle_factory
        self.scheduler=scheduler; self.ttl_seconds=float(ttl_seconds)
        self._lock=asyncio.Lock(); self._leases={}

    async def create(self,*,priority:int,source:str,metadata:JobMetadata|None=None)->dict[str,object]:
        metadata = metadata or JobMetadata(capability="external-reservation")
        if not metadata.workload:
            metadata = replace(metadata, workload=external_workload(self.scheduler.registry))
        # Acquire the registry lock first: cancellation waiting for it must not
        # leave a scheduler reservation without a lease/reaper owner.
        async with self._lock:
            reservation = await self.scheduler.reserve(priority=priority, source=source, metadata=metadata)
            now = monotonic()
            lease_id = secrets.token_urlsafe(24)
            rec = _Lease(lease_id, reservation.job_id, reservation.priority, reservation.source, now, now)
            self._leases[lease_id] = rec
        try:
            return await self.describe(lease_id)
        except BaseException:
            await asyncio.shield(self.release(lease_id))
            raise

    async def describe(self,lease_id:str)->dict[str,object]:
        rec=await self._record(lease_id); status=await self.scheduler.job_status(rec.job_id)
        if status is None:
            async with self._lock: self._leases.pop(lease_id,None)
            raise ResourceLeaseNotFound("resource lease no longer exists")
        return {"lease_id":lease_id,**status}

    async def heartbeat(self,lease_id:str)->dict[str,object]:
        async with self._lock:
            rec=self._leases.get(lease_id)
            if rec is None: raise ResourceLeaseNotFound("resource lease not found")
            rec.last_heartbeat=monotonic()
        return await self.describe(lease_id)

    async def begin_use(self, lease_id: str, *, workload: WorkloadBinding | None = None) -> SchedulerTicket:
        async with self._lock:
            rec = self._leases.get(lease_id)
            if rec is None:
                raise ResourceLeaseNotFound("resource lease not found")
            if self.scheduler.admission_blocked:
                raise ResourceLeaseNotActive("GPU admission blocked")
            ticket = await self.scheduler.active_ticket(rec.job_id)
            if ticket is None or rec.in_use or rec.external_use_id or rec.release_when_idle:
                raise ResourceLeaseNotActive("resource lease is not available")
            if workload is not None:
                workload.validate(self.scheduler.registry)
                status = await self.scheduler.job_status(rec.job_id)
                allowed = status["job"]["workload"]
                if {"provider": workload.provider, "node": workload.node, "capability": workload.capability} not in allowed:
                    raise ResourceLeaseNotAllowed("workload outside resource lease")
            rec.in_use = 1
            rec.last_heartbeat = monotonic()
            return ticket

    async def begin_external_use(self, lease_id: str, workload: WorkloadBinding) -> str:
        async with self._lock:
            rec = self._leases.get(lease_id)
            if rec is None:
                raise ResourceLeaseNotFound("resource lease not found")
            if self.scheduler.admission_blocked:
                raise ResourceLeaseNotActive("GPU admission blocked")
            ticket = await self.scheduler.active_ticket(rec.job_id)
            if ticket is None or rec.in_use or rec.external_use_id or rec.release_when_idle:
                raise ResourceLeaseNotActive("resource lease is not available")
            workload.validate(self.scheduler.registry)
            status = await self.scheduler.job_status(rec.job_id)
            if asdict(workload) not in status["job"]["workload"]:
                raise ResourceLeaseNotAllowed("workload outside resource lease")
            self.require_external_provider(workload.provider)
            # Pin before I/O, including cancellation/disconnect. Failure must
            # retain ownership even when the worker releases or stops heartbeats.
            rec.external_use_id = secrets.token_urlsafe(24)
            rec.external_workload = workload
            if workload.provider == "vision-local":
                owner = VisionOwner(lease_id, rec.external_use_id, rec.job_id)
                adapter = VisionLifecycleAdapter(self.vision_executor, owner,
                    lambda: (self._leases.get(lease_id) is rec
                             and rec.external_use_id == owner.use_id
                             and rec.job_id == owner.job_id
                             and not self.scheduler.admission_blocked))
            elif workload.provider == "comfyui-local" and self.comfy_lifecycle_factory is not None:
                adapter = self.comfy_lifecycle_factory()
            else:
                adapter = lifecycle_for(workload.provider, external=True)
            rec.lifecycle = adapter
            rec.in_use = 1
        try:
            await adapter.prepare(self.residency)
        except BaseException as exc:
            self._block()
            if isinstance(adapter, VisionLifecycleAdapter) and isinstance(exc, Exception):
                raise EngineLifecycleError("Vision preparation failed closed") from exc
            raise
        finally:
            # No await: identity remains pinned throughout the transition.
            rec.in_use = 0
            rec.last_heartbeat = monotonic()
        return rec.external_use_id

    async def verify_external_use(self, lease_id: str, use_id: str):
        # This endpoint is an execution authorization, not a read-only status.
        async with self._lock:
            rec = self._leases.get(lease_id)
            if (rec is None or rec.external_use_id != use_id or rec.in_use
                    or self.scheduler.admission_blocked
                    or rec.external_workload is None):
                return None
            if await self.scheduler.active_ticket(rec.job_id) is None:
                self._block()
                return None
            try:
                verified = rec.lifecycle.verify_active(self.residency)
            except BaseException:
                self._block()
                raise
            if not verified:
                self._block()
            return rec.external_workload if verified else None

    async def end_external_use(self, lease_id: str, use_id: str) -> bool:
        async with self._lock:
            rec = self._leases.get(lease_id)
            if rec is not None and rec.external_use_id is None and rec.ended_use_id == use_id:
                return True
            if rec is None or rec.external_use_id != use_id:
                return False
            if rec.in_use:
                raise ResourceLeaseNotActive("GPU transition already in progress")
            if await self.scheduler.active_ticket(rec.job_id) is None:
                self._block()
                raise ResourceLeaseNotActive("resource lease is no longer active")
            rec.in_use = 1
        try:
            await rec.lifecycle.release(self.residency)
        except BaseException as exc:
            self._block()
            rec.in_use = 0
            rec.last_heartbeat = monotonic()
            if isinstance(rec.lifecycle, VisionLifecycleAdapter) and isinstance(exc, Exception):
                raise EngineLifecycleError("Vision cleanup failed closed") from exc
            raise
        # Reacquiring can be cancelled. Keep external ownership in that case;
        # safe false-negative, never reopen admission on incomplete cleanup.
        try:
            async with self._lock:
                if rec.release_when_idle:
                    await self.scheduler.release_job(rec.job_id)
                rec.in_use = 0
                rec.last_heartbeat = monotonic()
                rec.ended_use_id = use_id
                rec.external_use_id = None
                rec.external_workload = None
                rec.lifecycle = None
                if rec.release_when_idle:
                    self._leases.pop(lease_id, None)
                return True
        except BaseException:
            self._block()
            raise

    def require_external_provider(self, provider):
        if provider == "vision-local":
            runtime = self.vision_executor
            if (runtime is None or runtime.resource_id != "local-primary"
                    or runtime.available() is not True or self.scheduler.max_concurrency != 1):
                raise ResourceLeaseNotAllowed("Vision executor NOT_ADMITTED")
            return
        try:
            lifecycle_for(provider, external=True)
        except EngineLifecycleError as exc:
            raise ResourceLeaseNotAllowed(str(exc)) from exc

    def _block(self):
        self.scheduler.admission_blocked = True
        if self.residency is not None:
            self.residency.state = "blocked"
            self.residency._dirty()

    async def inspect_vision(self, lease_id: str, use_id: str, image_id: str):
        if not valid_image_id(image_id):
            raise ValueError("invalid registered image ID")
        async with self._lock:
            rec = self._leases.get(lease_id)
            if (rec is None or rec.external_use_id != use_id or rec.in_use
                    or rec.release_when_idle or self.scheduler.admission_blocked
                    or not isinstance(rec.lifecycle, VisionLifecycleAdapter)):
                raise ResourceLeaseNotActive("Vision ownership unavailable")
            if await self.scheduler.active_ticket(rec.job_id) is None:
                self._block()
                raise ResourceLeaseNotActive("Vision reservation not active")
            if rec.lifecycle.completed:
                raise ResourceLeaseNotActive("Vision use already executed")
            rec.in_use = 1
        try:
            return await rec.lifecycle.execute(self.residency, image_id)
        except BaseException as exc:
            self._block()
            if isinstance(exc, Exception):
                raise EngineLifecycleError("Vision inspection failed closed") from exc
            raise
        finally:
            rec.in_use = 0
            rec.last_heartbeat = monotonic()

    def engine_activity(self):
        """Trusted diagnostic view only; never used to grant GPU ownership."""
        for rec in self._leases.values():
            if isinstance(rec.lifecycle, VisionLifecycleAdapter) and rec.external_use_id:
                return {"job_id": rec.job_id, "provider": "vision-local",
                        "state": "SWITCHING" if rec.lifecycle.phase != "execute" else "RUNNING"}
        return None

    async def end_use(self,lease_id:str,*,release:bool=False)->None:
        async with self._lock:
            rec=self._leases.get(lease_id)
            if rec is None: return
            rec.in_use=max(0,rec.in_use-1); rec.last_heartbeat=monotonic()
            if release: rec.release_when_idle=True
            if rec.in_use==0 and not rec.external_use_id and rec.release_when_idle:
                await self.scheduler.release_job(rec.job_id)
                self._leases.pop(lease_id,None)

    async def release(self,lease_id:str)->bool:
        async with self._lock:
            rec=self._leases.get(lease_id)
            if rec is None: return False
            if rec.in_use or rec.external_use_id:
                rec.release_when_idle=True; return True
            await self.scheduler.release_job(rec.job_id)
            self._leases.pop(lease_id,None)
            return True

    async def reap_expired(self)->int:
        now=monotonic()
        async with self._lock:
            expired=[lid for lid,r in self._leases.items() if r.in_use==0 and not r.external_use_id and now-r.last_heartbeat>self.ttl_seconds]
            for lid in expired:
                rec=self._leases[lid]
                await self.scheduler.release_job(rec.job_id, state=JobLifecycle.EXPIRED)
                self._leases.pop(lid)
        return len(expired)

    async def snapshot(self)->dict[str,object]:
        async with self._lock:
            leases = []
            for rec in sorted(self._leases.values(), key=lambda item: item.job_id):
                status = await self.scheduler.job_status(rec.job_id)
                leases.append({"job_id": rec.job_id, "priority": rec.priority,
                               "source": rec.source, "in_use": rec.in_use,
                               "release_when_idle": rec.release_when_idle,
                               "external_in_use": rec.external_use_id is not None,
                               "external_workload": asdict(rec.external_workload) if rec.external_workload else None,
                               "job": status["job"] if status else None})
            return {"lease_count": len(leases), "leases": leases}


    async def _record(self,lease_id:str)->_Lease:
        async with self._lock:
            rec=self._leases.get(str(lease_id))
            if rec is None: raise ResourceLeaseNotFound("resource lease not found")
            return rec
