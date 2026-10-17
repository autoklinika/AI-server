"""Internal DEV CPU admission. No GPU authority, HTTP API or command input.

Runtime injection is trusted test code, never configuration or worker evidence.
The fixed N5 program performs only stdlib CPU work and starts a new session.
This is not a device sandbox or a descendant containment boundary.
"""
from __future__ import annotations

import asyncio
import math
import os
from pathlib import Path

from .jobs import JobMetadata
from .managed_worker_observer import Runtime as WorkerRuntime, WorkerObserver
from .scheduler import PriorityScheduler


class ManagedWorker:
    gpu_status = "NOT_VERIFIED"
    gpu_admission = "NOT_ADMITTED"

    def __init__(self, scheduler: PriorityScheduler, marker: Path, *,
                 enabled: bool = False, test_runtime: WorkerRuntime | None = None):
        self.scheduler = scheduler
        self._marker = marker
        self._enabled = enabled
        self._runtime = test_runtime
        self._owner: asyncio.Task | None = None
        self._closed = False
        self.state = "DISABLED" if not enabled else "READY"
        # Disabled mode is inert: old DEV markers must never affect production.
        # Only an explicitly enabled pilot may examine its owned marker.
        if enabled:
            try:
                if marker.exists():
                    self._block()
            except OSError:
                self._block()

    def _block(self):
        self.state = "DIRTY"
        self.scheduler.admission_blocked = True
        # The observer creates/fsyncs this before spawning. Also cover failures
        # before spawn, cancellation while queued, and persistence failures.
        try:
            with self._marker.open("a") as record:
                record.write("DIRTY: internal CPU admission unresolved\n")
                record.flush()
                os.fsync(record.fileno())
            self._sync_directory()
        except OSError:
            pass  # In-memory latch and retained ownership still fail closed.

    def _sync_directory(self):
        fd = os.open(self._marker.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    async def run(self, workload: str = "synthetic-cpu-v1", *, timeout: float = 2.0):
        if type(workload) is not str or workload != "synthetic-cpu-v1":
            raise ValueError("only fixed synthetic-cpu-v1 is allowlisted")
        if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 < timeout <= 10:
            raise ValueError("timeout must be finite, positive and at most 10 seconds")
        if (not self._enabled or self._closed or self.state == "DIRTY"
                or self.scheduler.admission_blocked):
            raise RuntimeError("managed CPU admission unavailable; GPU NOT_ADMITTED")
        if self.scheduler.max_concurrency != 1:
            raise RuntimeError("managed CPU requires the existing single-slot scheduler")
        if self._owner is not None and not self._owner.done():
            raise RuntimeError("managed worker already owned")
        # No await before ownership is published: duplicate callers cannot race.
        self._owner = asyncio.create_task(self._execute(timeout))
        self._owner.add_done_callback(self._consume_exception)
        try:
            result = await asyncio.shield(self._owner)
        except asyncio.CancelledError:
            self._block()
            raise
        if result != "PROCESS_CLOSED":
            raise RuntimeError("managed CPU attempt unresolved; scheduler blocked")
        return result

    @staticmethod
    def _consume_exception(task):
        if not task.cancelled():
            task.exception()

    async def _execute(self, timeout):
        try:
            ticket = await asyncio.wait_for(self.scheduler.acquire(
                priority=100, source="internal-managed-cpu",
                metadata=JobMetadata(capability="external-reservation")), timeout)
            if self.state == "DIRTY" or self._closed:
                raise RuntimeError("attempt cancelled before launch")
            await self.scheduler.mark_running(ticket.job_id)
            if self.state == "DIRTY" or self._closed:
                raise RuntimeError("attempt cancelled before launch")
            observer = WorkerObserver(self._marker, runtime=self._runtime)
            self.state = "RUNNING"

            def observe():
                observer.start()
                return observer.observe(timeout=timeout)

            # A timeout cannot stop a thread or revoke a child handle. Keep the
            # scheduler owner on any uncertainty; never use scheduler.slot().
            result = await asyncio.wait_for(asyncio.to_thread(observe), timeout)
            if result != "PROCESS_CLOSED" or self.state == "DIRTY" or self._closed:
                raise RuntimeError("CPU process closure unverified")
            self._marker.unlink()
            self._sync_directory()
            await self.scheduler.release(ticket)
            self.state = "PROCESS_CLOSED"
            return self.state
        except BaseException:
            # The caller can have been cancelled while this shielded task still
            # owns the slot. Do not leak an unobserved exception into the event
            # loop; report DIRTY and retain the fail-closed admission latch.
            self._block()
            return "DIRTY"

    async def close(self):
        self._closed = True
        if self._owner is not None and not self._owner.done():
            self._block()
            # Do not cancel launch/observation or send signals. Its own bounded
            # waits finish asynchronously, retaining the slot on failure.
