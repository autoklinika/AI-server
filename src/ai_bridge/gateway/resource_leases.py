from __future__ import annotations
import asyncio, secrets
from dataclasses import dataclass
from time import monotonic
from .scheduler import PriorityScheduler, SchedulerTicket

class ResourceLeaseError(RuntimeError): pass
class ResourceLeaseNotFound(ResourceLeaseError): pass
class ResourceLeaseNotActive(ResourceLeaseError): pass

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

class ResourceLeaseRegistry:
    def __init__(self,scheduler:PriorityScheduler,*,ttl_seconds:float=45.0)->None:
        if ttl_seconds<=0: raise ValueError("ttl_seconds must be > 0")
        self.scheduler=scheduler; self.ttl_seconds=float(ttl_seconds)
        self._lock=asyncio.Lock(); self._leases={}

    async def create(self,*,priority:int,source:str)->dict[str,object]:
        reservation=await self.scheduler.reserve(priority=priority,source=source)
        now=monotonic(); lease_id=secrets.token_urlsafe(24)
        rec=_Lease(lease_id,reservation.job_id,reservation.priority,reservation.source,now,now)
        async with self._lock: self._leases[lease_id]=rec
        status=await self.scheduler.job_status(rec.job_id)
        assert status is not None
        return {"lease_id":lease_id,**status}

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

    async def begin_use(self,lease_id:str)->SchedulerTicket:
        rec=await self._record(lease_id); ticket=await self.scheduler.active_ticket(rec.job_id)
        if ticket is None: raise ResourceLeaseNotActive("resource lease is not active")
        async with self._lock:
            rec=self._leases.get(lease_id)
            if rec is None: raise ResourceLeaseNotFound("resource lease not found")
            rec.in_use+=1; rec.last_heartbeat=monotonic()
        return ticket

    async def end_use(self,lease_id:str,*,release:bool=False)->None:
        job_id=None
        async with self._lock:
            rec=self._leases.get(lease_id)
            if rec is None: return
            rec.in_use=max(0,rec.in_use-1); rec.last_heartbeat=monotonic()
            if release: rec.release_when_idle=True
            if rec.in_use==0 and rec.release_when_idle:
                job_id=rec.job_id; self._leases.pop(lease_id,None)
        if job_id is not None: await self.scheduler.release_job(job_id)

    async def release(self,lease_id:str)->bool:
        job_id=None
        async with self._lock:
            rec=self._leases.get(lease_id)
            if rec is None: return False
            if rec.in_use:
                rec.release_when_idle=True; return True
            job_id=rec.job_id; self._leases.pop(lease_id,None)
        await self.scheduler.release_job(job_id); return True

    async def reap_expired(self)->int:
        now=monotonic()
        async with self._lock:
            expired=[lid for lid,r in self._leases.items() if r.in_use==0 and now-r.last_heartbeat>self.ttl_seconds]
        removed=0
        for lid in expired:
            if await self.release(lid): removed+=1
        return removed

    async def snapshot(self)->dict[str,object]:
        async with self._lock:
            return {"lease_count":len(self._leases),"leases":[{"job_id":r.job_id,"priority":r.priority,"source":r.source,"in_use":r.in_use,"release_when_idle":r.release_when_idle} for r in sorted(self._leases.values(),key=lambda x:x.job_id)]}

    async def _record(self,lease_id:str)->_Lease:
        async with self._lock:
            rec=self._leases.get(str(lease_id))
            if rec is None: raise ResourceLeaseNotFound("resource lease not found")
            return rec
