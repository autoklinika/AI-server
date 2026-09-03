from __future__ import annotations

import asyncio
import heapq
from contextlib import asynccontextmanager
from dataclasses import dataclass
from itertools import count
from time import monotonic
from typing import AsyncIterator


class SchedulerQueueFull(RuntimeError):
    """Raised when the waiting queue reached its configured limit."""


@dataclass(frozen=True)
class SchedulerTicket:
    job_id: int
    priority: int
    source: str
    queued_at_monotonic: float
    started_at_monotonic: float

    @property
    def wait_ms(self) -> float:
        return max(0.0, (self.started_at_monotonic - self.queued_at_monotonic) * 1000.0)


@dataclass
class _PendingJob:
    job_id: int
    priority: int
    sequence: int
    source: str
    queued_at_monotonic: float
    future: asyncio.Future[SchedulerTicket]


class PriorityScheduler:
    """Priority admission scheduler used before local inference.

    Lower numeric priority wins. Jobs with the same priority are admitted FIFO.
    The scheduler deliberately does not preempt an already-running request; it
    decides which waiting request receives the next free execution slot.
    """

    def __init__(self, *, max_concurrency: int = 1, max_queue_size: int = 128) -> None:
        if max_concurrency < 1:
            raise ValueError("max_concurrency must be >= 1")
        if max_queue_size < 1:
            raise ValueError("max_queue_size must be >= 1")
        self.max_concurrency = max_concurrency
        self.max_queue_size = max_queue_size
        self._lock = asyncio.Lock()
        self._sequence = count(1)
        self._heap: list[tuple[int, int, int]] = []
        self._pending: dict[int, _PendingJob] = {}
        self._active: dict[int, SchedulerTicket] = {}

    async def acquire(self, *, priority: int, source: str) -> SchedulerTicket:
        source = source.strip() or "unknown"
        loop = asyncio.get_running_loop()
        sequence = next(self._sequence)
        job_id = sequence
        future: asyncio.Future[SchedulerTicket] = loop.create_future()
        pending = _PendingJob(
            job_id=job_id,
            priority=int(priority),
            sequence=sequence,
            source=source,
            queued_at_monotonic=monotonic(),
            future=future,
        )
        async with self._lock:
            self._purge_cancelled_locked()
            if len(self._pending) >= self.max_queue_size:
                raise SchedulerQueueFull(
                    f"scheduler queue is full ({self.max_queue_size} waiting jobs)"
                )
            self._pending[job_id] = pending
            heapq.heappush(self._heap, (pending.priority, pending.sequence, pending.job_id))
            self._dispatch_locked()

        try:
            return await future
        except asyncio.CancelledError:
            # Cancellation can happen while queued or in the narrow window after
            # _dispatch_locked() granted this job a slot but before this task
            # resumed from ``await future``. Clean up both states so an
            # abandoned admission can never leak an active slot.
            async with self._lock:
                self._pending.pop(job_id, None)
                self._active.pop(job_id, None)
                self._dispatch_locked()
            raise

    async def release(self, ticket: SchedulerTicket) -> None:
        async with self._lock:
            self._active.pop(ticket.job_id, None)
            self._dispatch_locked()

    @asynccontextmanager
    async def slot(self, *, priority: int, source: str) -> AsyncIterator[SchedulerTicket]:
        ticket = await self.acquire(priority=priority, source=source)
        try:
            yield ticket
        finally:
            await self.release(ticket)

    async def snapshot(self) -> dict[str, object]:
        async with self._lock:
            self._purge_cancelled_locked()
            queued = sorted(
                self._pending.values(),
                key=lambda job: (job.priority, job.sequence),
            )
            active = sorted(self._active.values(), key=lambda ticket: ticket.job_id)
            return {
                "max_concurrency": self.max_concurrency,
                "max_queue_size": self.max_queue_size,
                "active_count": len(active),
                "queued_count": len(queued),
                "active": [
                    {
                        "job_id": item.job_id,
                        "priority": item.priority,
                        "source": item.source,
                        "wait_ms": round(item.wait_ms, 3),
                    }
                    for item in active
                ],
                "queued": [
                    {
                        "job_id": item.job_id,
                        "priority": item.priority,
                        "source": item.source,
                    }
                    for item in queued
                ],
            }

    def _purge_cancelled_locked(self) -> None:
        cancelled = [
            job_id for job_id, pending in self._pending.items() if pending.future.cancelled()
        ]
        for job_id in cancelled:
            self._pending.pop(job_id, None)

    def _dispatch_locked(self) -> None:
        self._purge_cancelled_locked()
        while len(self._active) < self.max_concurrency and self._heap:
            _priority, _sequence, job_id = heapq.heappop(self._heap)
            pending = self._pending.pop(job_id, None)
            if pending is None or pending.future.cancelled():
                continue
            ticket = SchedulerTicket(
                job_id=pending.job_id,
                priority=pending.priority,
                source=pending.source,
                queued_at_monotonic=pending.queued_at_monotonic,
                started_at_monotonic=monotonic(),
            )
            self._active[job_id] = ticket
            pending.future.set_result(ticket)
