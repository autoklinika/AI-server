"""CPU only; injected runtimes never access devices or signal processes."""
import asyncio
from dataclasses import replace
from pathlib import Path
import threading
from types import SimpleNamespace

import httpx
import pytest

from ai_bridge.gateway.app import create_gateway_app
from ai_bridge.gateway.managed_worker import ManagedWorker
from ai_bridge.gateway.managed_worker_observer import Identity
from ai_bridge.gateway.scheduler import PriorityScheduler
from ai_bridge.settings import Settings


@pytest.fixture
def anyio_backend():
    return "asyncio"


class CPU:
    def __init__(self, failure=None):
        self.failure = failure
        self.started = threading.Event()
        self.finish = threading.Event()
        self.identities = 0

    def spawn(self):
        self.started.set()
        if self.failure == "launch":
            raise OSError("launch")
        if self.failure == "slow-launch":
            self.finish.wait(2)
        return SimpleNamespace(pid=123)

    def identity(self, child, scope):
        self.identities += 1
        identity = Identity("boot", 123, 456, 123, 123, scope)
        if self.failure == "missing" and self.identities > 1:
            raise FileNotFoundError()
        if self.failure == "incarnation" and self.identities > 1:
            return replace(identity, birth_ticks=999)
        return identity

    def wait(self, child, timeout):
        if not self.finish.wait(timeout):
            raise TimeoutError()
        return 1 if self.failure == "crash" else 0


async def started(cpu):
    async with asyncio.timeout(2):
        while not cpu.started.is_set():
            await asyncio.sleep(.001)


@pytest.mark.anyio
async def test_same_app_scheduler_blocks_chat_and_releases(tmp_path):
    app = create_gateway_app(Settings(gateway_gpu_marker=tmp_path / "gpu"),
        upstream_transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"ok": True})))
    async with app.router.lifespan_context(app):
        internal = app.state.managed_worker
        assert internal.scheduler is app.state.scheduler is app.state.resource_leases.scheduler
        with pytest.raises(RuntimeError):
            await internal.run()
        cpu = CPU()
        worker = ManagedWorker(internal.scheduler, tmp_path / "attempt", enabled=True, test_runtime=cpu)
        run = asyncio.create_task(worker.run())
        await started(cpu)
        try:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                chat = asyncio.create_task(client.post("/api/chat", json={"model": "test", "messages": []}))
                await asyncio.sleep(.02)
                assert not chat.done()
                with pytest.raises(RuntimeError):
                    await worker.run()
                cpu.finish.set()
                assert await run == "PROCESS_CLOSED"
                assert (await asyncio.wait_for(chat, 2)).status_code == 200
            assert worker.gpu_status == "NOT_VERIFIED"
            assert worker.gpu_admission == "NOT_ADMITTED"
            assert not (tmp_path / "attempt").exists()
        finally:
            cpu.finish.set()
            await asyncio.gather(run, return_exceptions=True)


@pytest.mark.anyio
@pytest.mark.parametrize("failure", ["launch", "missing", "incarnation", "crash", "timeout", "cancel", "slow-launch", "shutdown"])
async def test_uncertainty_retains_slot_and_durable_latch(tmp_path, failure):
    scheduler = PriorityScheduler()
    cpu = CPU(failure)
    worker = ManagedWorker(scheduler, tmp_path / "attempt", enabled=True, test_runtime=cpu)
    task = asyncio.create_task(worker.run(timeout=.1 if failure == "timeout" else 2))
    await started(cpu)
    try:
        if failure in ("cancel", "slow-launch"):
            task.cancel()
        if failure == "shutdown":
            await worker.close()
        if failure != "timeout":
            cpu.finish.set()
        with pytest.raises((RuntimeError, OSError, TimeoutError, asyncio.CancelledError)):
            await task
        cpu.finish.set()
        await asyncio.gather(worker._owner, return_exceptions=True)
        assert scheduler.admission_blocked
        assert (await scheduler.snapshot())["active_count"] == 1
        assert (tmp_path / "attempt").exists()
        with pytest.raises(RuntimeError):
            await worker.run()
        replacement = ManagedWorker(PriorityScheduler(), tmp_path / "attempt", enabled=True)
        assert replacement.scheduler.admission_blocked
    finally:
        cpu.finish.set()


@pytest.mark.anyio
async def test_queue_cancel_and_n2_cannot_launch(tmp_path):
    scheduler = PriorityScheduler()
    from ai_bridge.gateway.jobs import JobMetadata
    ticket = await scheduler.acquire(priority=1, source="chat", metadata=JobMetadata(capability="external-reservation"))
    cpu = CPU()
    worker = ManagedWorker(scheduler, tmp_path / "attempt", enabled=True, test_runtime=cpu)
    task = asyncio.create_task(worker.run(timeout=.05))
    await asyncio.sleep(.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await scheduler.release(ticket)
    await asyncio.gather(worker._owner, return_exceptions=True)
    assert scheduler.admission_blocked and not cpu.started.is_set()
    n2 = ManagedWorker(PriorityScheduler(admission_strategy="n2-dev-blocked"), tmp_path / "n2", enabled=True, test_runtime=cpu)
    with pytest.raises(RuntimeError):
        await n2.run()
    assert not cpu.started.is_set()


@pytest.mark.anyio
@pytest.mark.parametrize("kwargs", [{"workload": x} for x in ["gpu", "python", "/bin/sh", "", None, {}, "synthetic-cpu-v2"]] + [{"timeout": x} for x in [True, 0, -1, float("inf"), float("nan"), 11, "1"]])
async def test_invalid_input_never_launches(tmp_path, kwargs):
    cpu = CPU()
    worker = ManagedWorker(PriorityScheduler(), tmp_path / "attempt", enabled=True, test_runtime=cpu)
    with pytest.raises(ValueError):
        await worker.run(**kwargs)
    assert not cpu.started.is_set() and not (tmp_path / "attempt").exists()


@pytest.mark.anyio
async def test_fixed_real_cpu_and_successive_runs(tmp_path):
    worker = ManagedWorker(PriorityScheduler(), tmp_path / "attempt", enabled=True)
    assert await worker.run() == "PROCESS_CLOSED"
    assert await worker.run() == "PROCESS_CLOSED"
    assert (await worker.scheduler.snapshot())["active_count"] == 0


@pytest.mark.anyio
async def test_disabled_pilot_ignores_stale_dev_marker_without_blocking_gateway(tmp_path):
    marker = tmp_path / 'old-dev-only-marker'
    marker.write_text('old untrusted CPU attempt')
    scheduler = PriorityScheduler()
    pilot = ManagedWorker(scheduler, marker)  # default OFF
    assert pilot.state == 'DISABLED'
    assert scheduler.admission_blocked is False
    with pytest.raises(RuntimeError):
        await pilot.run()
    assert scheduler.admission_blocked is False
    ticket = await scheduler.acquire(priority=50, source='normal-gateway')
    await scheduler.release(ticket)
    assert marker.exists()
