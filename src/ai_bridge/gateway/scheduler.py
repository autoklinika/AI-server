from __future__ import annotations
import asyncio, heapq
from contextlib import asynccontextmanager
from dataclasses import dataclass
from itertools import count
from time import monotonic
from typing import AsyncIterator

class SchedulerQueueFull(RuntimeError):
    pass

@dataclass(frozen=True)
class SchedulerTicket:
    job_id: int
    priority: int
    source: str
    queued_at_monotonic: float
    started_at_monotonic: float
    @property
    def wait_ms(self) -> float:
        return max(0.0, (self.started_at_monotonic-self.queued_at_monotonic)*1000.0)

@dataclass(frozen=True)
class SchedulerReservation:
    job_id: int
    priority: int
    source: str
    queued_at_monotonic: float

@dataclass
class _PendingJob:
    job_id: int
    priority: int
    sequence: int
    source: str
    queued_at_monotonic: float
    future: asyncio.Future[SchedulerTicket]

class PriorityScheduler:
    def __init__(self, *, max_concurrency:int=1, max_queue_size:int=128)->None:
        if max_concurrency < 1: raise ValueError("max_concurrency must be >= 1")
        if max_queue_size < 1: raise ValueError("max_queue_size must be >= 1")
        self.max_concurrency=max_concurrency; self.max_queue_size=max_queue_size
        self._lock=asyncio.Lock(); self._sequence=count(1)
        self._heap=[]; self._pending={}; self._active={}

    async def _enqueue(self, *, priority:int, source:str)->_PendingJob:
        source=source.strip() or "unknown"; seq=next(self._sequence)
        pending=_PendingJob(seq,int(priority),seq,source,monotonic(),asyncio.get_running_loop().create_future())
        async with self._lock:
            self._purge_cancelled_locked()
            if len(self._pending) >= self.max_queue_size:
                raise SchedulerQueueFull(f"scheduler queue is full ({self.max_queue_size} waiting jobs)")
            self._pending[pending.job_id]=pending
            heapq.heappush(self._heap,(pending.priority,pending.sequence,pending.job_id))
            self._dispatch_locked()
        return pending

    async def reserve(self, *, priority:int, source:str)->SchedulerReservation:
        p=await self._enqueue(priority=priority,source=source)
        return SchedulerReservation(p.job_id,p.priority,p.source,p.queued_at_monotonic)

    async def acquire(self, *, priority:int, source:str)->SchedulerTicket:
        p=await self._enqueue(priority=priority,source=source)
        try:
            return await p.future
        except asyncio.CancelledError:
            async with self._lock:
                self._pending.pop(p.job_id,None); self._active.pop(p.job_id,None); self._dispatch_locked()
            raise

    async def release(self, ticket:SchedulerTicket)->None:
        await self.release_job(ticket.job_id)

    async def release_job(self, job_id:int)->bool:
        removed=False
        async with self._lock:
            p=self._pending.pop(int(job_id),None)
            if p is not None:
                removed=True
                if not p.future.done(): p.future.cancel()
            if self._active.pop(int(job_id),None) is not None: removed=True
            if removed: self._dispatch_locked()
        return removed

    async def active_ticket(self, job_id:int)->SchedulerTicket|None:
        async with self._lock: return self._active.get(int(job_id))

    async def job_status(self, job_id:int)->dict[str,object]|None:
        async with self._lock:
            self._purge_cancelled_locked(); job_id=int(job_id)
            a=self._active.get(job_id)
            if a is not None:
                return {"job_id":a.job_id,"state":"active","priority":a.priority,"source":a.source,
                        "queue_position":0,"wait_ms":round(a.wait_ms,3)}
            p=self._pending.get(job_id)
            if p is None: return None
            ordered=sorted(self._pending.values(),key=lambda j:(j.priority,j.sequence))
            pos=next((i for i,j in enumerate(ordered,1) if j.job_id==job_id),None)
            return {"job_id":p.job_id,"state":"queued","priority":p.priority,"source":p.source,
                    "queue_position":pos,"wait_ms":round(max(0.0,(monotonic()-p.queued_at_monotonic)*1000.0),3)}

    @asynccontextmanager
    async def slot(self, *, priority:int, source:str)->AsyncIterator[SchedulerTicket]:
        t=await self.acquire(priority=priority,source=source)
        try: yield t
        finally: await self.release(t)

    async def snapshot(self)->dict[str,object]:
        async with self._lock:
            self._purge_cancelled_locked()
            queued=sorted(self._pending.values(),key=lambda j:(j.priority,j.sequence))
            active=sorted(self._active.values(),key=lambda t:t.job_id)
            return {"max_concurrency":self.max_concurrency,"max_queue_size":self.max_queue_size,
                    "active_count":len(active),"queued_count":len(queued),
                    "active":[{"job_id":x.job_id,"priority":x.priority,"source":x.source,"wait_ms":round(x.wait_ms,3)} for x in active],
                    "queued":[{"job_id":x.job_id,"priority":x.priority,"source":x.source} for x in queued]}

    def _purge_cancelled_locked(self)->None:
        for job_id in [i for i,p in self._pending.items() if p.future.cancelled()]:
            self._pending.pop(job_id,None)

    def _dispatch_locked(self)->None:
        self._purge_cancelled_locked()
        while len(self._active)<self.max_concurrency and self._heap:
            _,_,job_id=heapq.heappop(self._heap); p=self._pending.pop(job_id,None)
            if p is None or p.future.cancelled(): continue
            t=SchedulerTicket(p.job_id,p.priority,p.source,p.queued_at_monotonic,monotonic())
            self._active[job_id]=t
            if not p.future.done(): p.future.set_result(t)
