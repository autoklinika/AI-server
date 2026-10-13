from __future__ import annotations
import asyncio, secrets
from dataclasses import asdict, dataclass, replace
from time import monotonic
from .admission import WorkloadBinding, external_workload
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

class ResourceLeaseRegistry:
    def __init__(self,scheduler:PriorityScheduler,*,ttl_seconds:float=45.0, residency=None, vision_enabled:bool=False, vision_attestation=None)->None:
        if ttl_seconds<=0: raise ValueError("ttl_seconds must be > 0")
        self.residency = residency
        self.scheduler=scheduler; self.ttl_seconds=float(ttl_seconds)
        self.vision_enabled=bool(vision_enabled)
        self.vision_attestation=vision_attestation
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

    async def begin_external_use(self, lease_id: str, workload: WorkloadBinding, *, worker_pid: int | None = None, scope_path: str | None = None) -> str:
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
            if workload.provider == "vision-local":
                if (not self.vision_enabled or workload.capability != "image-analysis"
                        or type(worker_pid) is not int or worker_pid <= 1
                        or not isinstance(scope_path,str) or not scope_path):
                    raise ResourceLeaseNotAllowed("Vision external execution is unavailable")
                if self.residency:
                    # Read-only identity preflight BEFORE pinning GPU ownership.
                    # A worker which never existed must be rejected as a normal
                    # invalid request; it has not accessed any accelerator.
                    birth = self.residency.vision_process_probe(worker_pid)
                    scope = self.residency.vision_scope_probe(worker_pid)
                    members = self.residency.vision_cgroup_members(scope_path)
                    if (birth is None or birth <= 0 or scope != scope_path
                            or members is None or worker_pid not in members
                            or self.vision_attestation is None
                            or not self.vision_attestation(worker_pid)):
                        raise ResourceLeaseNotAllowed("Vision worker/scope is unavailable")
            elif workload.provider != "comfyui-local" or worker_pid is not None or scope_path is not None:
                raise ResourceLeaseNotAllowed("invalid external execution provider")
            # Pin before I/O, including cancellation/disconnect. Failure must
            # retain ownership even when the worker releases or stops heartbeats.
            rec.external_use_id = secrets.token_urlsafe(24)
            rec.external_workload = workload
            rec.in_use = 1
        try:
            if self.residency:
                if workload.provider == "vision-local":
                    await self.residency.enter_vision(worker_pid, scope_path)
                else:
                    await self.residency.enter_media()
        except BaseException:
            self.scheduler.admission_blocked = True
            if self.residency:
                # An admitted/partially transitioned GPU use cannot be
                # classified as clean from an exception. Persist marker even
                # if an identity race failed before enter_vision's _dirty().
                self.residency.fail_closed()
            raise
        finally:
            # No await: identity remains pinned throughout the transition.
            rec.in_use = 0
            rec.last_heartbeat = monotonic()
        return rec.external_use_id

    async def verify_external_use(self, lease_id: str, use_id: str):
        async with self._lock:
            rec = self._leases.get(lease_id)
            if (rec is None or rec.external_use_id != use_id or rec.in_use
                    or self.scheduler.admission_blocked
                    or (self.residency and self.residency.state !=
                        ("vision" if rec.external_workload and rec.external_workload.provider == "vision-local" else "media"))):
                return None
            return rec.external_workload

    async def end_external_use(self, lease_id: str, use_id: str) -> bool:
        async with self._lock:
            rec = self._leases.get(lease_id)
            if rec is not None and rec.external_use_id is None and rec.ended_use_id == use_id:
                return True
            if rec is None or rec.external_use_id != use_id:
                return False
            if rec.in_use:
                raise ResourceLeaseNotActive("GPU transition already in progress")
            rec.in_use = 1
        try:
            if self.residency:
                if rec.external_workload and rec.external_workload.provider == "vision-local":
                    await self.residency.leave_vision()
                else:
                    await self.residency.leave_media()
        except BaseException:
            self.scheduler.admission_blocked = True
            rec.in_use = 0
            rec.last_heartbeat = monotonic()
            raise
        # Reacquiring can be cancelled. Keep external ownership in that case;
        # safe false-negative, never reopen admission on incomplete cleanup.
        async with self._lock:
            rec.in_use = 0
            rec.last_heartbeat = monotonic()
            rec.ended_use_id = use_id
            rec.external_use_id = None
            rec.external_workload = None
            if rec.release_when_idle:
                await self.scheduler.release_job(rec.job_id)
                self._leases.pop(lease_id, None)
            return True

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
