import asyncio
from dataclasses import fields
from datetime import datetime
import json
from uuid import UUID

import httpx
import pytest

from ai_bridge.gateway.jobs import JobLifecycle as State, JobMetadata, JobState
from ai_bridge.gateway.priority import PriorityClass
from ai_bridge.gateway.resource_leases import ResourceLeaseRegistry
from ai_bridge.gateway.scheduler import PriorityScheduler, SchedulerQueueFull
from test_gateway_priority_classes import api_client, make_app, PATHS


@pytest.fixture
def anyio_backend():
    return "asyncio"


def assert_timestamps(job, expected):
    names = ["created_at", "queued_at", "admitted_at", "started_at", "finished_at"]
    stamps = [datetime.fromisoformat(job[name]) for name in names if job[name] is not None]
    assert len(stamps) == expected
    assert stamps == sorted(stamps)
    assert all(stamp.utcoffset().total_seconds() == 0 for stamp in stamps)


@pytest.mark.parametrize("start", list(State))
@pytest.mark.parametrize("end", list(State))
def test_explicit_transition_matrix(start, end):
    allowed = {
        State.SUBMITTED: {State.QUEUED, State.FAILED, State.CANCELLED},
        State.QUEUED: {State.ADMITTED, State.CANCELLED, State.EXPIRED},
        State.ADMITTED: {State.RUNNING, State.COMPLETED, State.FAILED, State.CANCELLED, State.EXPIRED},
        State.RUNNING: {State.COMPLETED, State.FAILED, State.CANCELLED, State.EXPIRED},
    }
    job = JobState("job_test", "req_test", "shared", "chat", None, state=start)
    if end in allowed.get(start, set()):
        assert job.transition(end).state == end
    else:
        with pytest.raises(ValueError, match="invalid job lifecycle transition"):
            job.transition(end)


def test_model_has_only_explicit_metadata_and_monotonic_wall_timestamps(monkeypatch):
    job = JobState.create(JobMetadata(), 73)
    assert job.priority_class is None
    assert {f.name for f in fields(job)} == {
        "job_id", "request_id", "domain", "capability", "priority_class", "state",
        "assigned_provider", "assigned_node", "created_at", "queued_at", "admitted_at",
        "started_at", "finished_at", "workload",
    }
    monkeypatch.setattr("ai_bridge.gateway.jobs.utc_now", lambda: datetime(2000, 1, 1, tzinfo=job.created_at.tzinfo))
    for state in [State.QUEUED, State.ADMITTED, State.RUNNING, State.COMPLETED]:
        job = job.transition(state)
    assert_timestamps(job.snapshot(), 5)


@pytest.mark.anyio
async def test_queue_admission_cancel_race_history_and_ids():
    scheduler = PriorityScheduler(history_limit=3)
    first = await scheduler.acquire(priority=50, source="first")
    waiting = asyncio.create_task(scheduler.acquire(priority=10, source="waiting"))
    await asyncio.sleep(0)
    queued = (await scheduler.snapshot())["queued"][0]
    assert queued["job"]["state"] == "queued"
    assert_timestamps(queued["job"], 2)
    await scheduler.release(first)
    waiting.cancel()  # after dispatch but before acquire resumes
    with pytest.raises(asyncio.CancelledError):
        await waiting
    status = await scheduler.snapshot()
    assert status["active_count"] == status["queued_count"] == 0
    assert status["recent_jobs"][-1]["state"] == "cancelled"
    assert_timestamps(status["recent_jobs"][-1], 4)
    assert await scheduler.job_status(first.job_id) is None
    ids = set()
    for _ in range(5):
        async with scheduler.slot(priority=100, source="private-source") as ticket:
            ids.add(ticket.platform_job_id)
            UUID(ticket.platform_job_id.removeprefix("job_"))
            UUID(ticket.request_id.removeprefix("req_"))
    assert len(ids) == 5
    assert len((await scheduler.snapshot())["recent_jobs"]) == 3
    assert "private-source" not in json.dumps((await scheduler.snapshot())["recent_jobs"])
    other = await PriorityScheduler().acquire(priority=100, source="other")
    assert other.platform_job_id not in ids


@pytest.mark.anyio
async def test_queue_rejection_and_queued_cancellation():
    scheduler = PriorityScheduler(max_queue_size=1)
    first = await scheduler.acquire(priority=50, source="first")
    waiting = asyncio.create_task(scheduler.acquire(priority=10, source="waiting"))
    await asyncio.sleep(0)
    with pytest.raises(SchedulerQueueFull):
        await scheduler.acquire(priority=100, source="overflow")
    rejected = (await scheduler.snapshot())["recent_jobs"][-1]
    assert rejected["state"] == "failed"
    assert_timestamps(rejected, 2)
    waiting.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiting
    cancelled = (await scheduler.snapshot())["recent_jobs"][-1]
    assert cancelled["state"] == "cancelled"
    assert_timestamps(cancelled, 3)
    await scheduler.release(first)


@pytest.mark.anyio
async def test_lease_reservation_lifecycle_release_deferred_and_expiry(monkeypatch):
    scheduler = PriorityScheduler()
    registry = ResourceLeaseRegistry(scheduler, ttl_seconds=10)
    lease = await registry.create(priority=50, source="external")
    job = lease["job"]
    assert lease["state"] == "active" and job["state"] == "admitted"
    assert job["capability"] == "external-reservation"
    assert job["assigned_provider"] is job["assigned_node"] is None
    await registry.begin_use(lease["lease_id"])
    await registry.release(lease["lease_id"])
    assert (await scheduler.snapshot())["active_count"] == 1
    await registry.end_use(lease["lease_id"])
    assert (await scheduler.snapshot())["recent_jobs"][-1]["state"] == "completed"
    blocker = await scheduler.acquire(priority=10, source="blocker")
    lease = await registry.create(priority=50, source="queued")
    await registry.release(lease["lease_id"])
    assert (await scheduler.snapshot())["recent_jobs"][-1]["state"] == "cancelled"
    lease = await registry.create(priority=50, source="queued-expiry")
    monkeypatch.setattr("ai_bridge.gateway.resource_leases.monotonic", lambda: float("inf"))
    assert await registry.reap_expired() == 1
    assert (await scheduler.snapshot())["recent_jobs"][-1]["state"] == "expired"
    await scheduler.release(blocker)


@pytest.mark.parametrize("path", PATHS)
@pytest.mark.anyio
async def test_http_job_metadata_and_correlation_do_not_copy_request(path, caplog):
    app = None
    async def handler(request):
        active = (await app.state.scheduler.snapshot())["active"][0]["job"]
        assert active["state"] == "running"
        assert active["assigned_provider"] == "ollama-local"
        assert active["assigned_node"] == "test-node"
        assert "priority_class" not in json.loads(request.content)
        return httpx.Response(200, json={"answer": "PRIVATE-RESPONSE"})
    app = make_app(handler, node_id="test-node")
    async with api_client(app) as client:
        response = await client.post(path, json={
            "prompt": "PRIVATE-PROMPT", "messages": [{"content": "PRIVATE-MESSAGE"}],
            "request_id": "PRIVATE-ID", "domain": "PRIVATE-DOMAIN",
            "model": "PRIVATE-MODEL", "priority_class": "critical",
        }, headers={"X-AI-Priority": "73"})
        status = (await client.get("/status")).json()
        job = status["recent_jobs"][-1]
        assert job["priority_class"] == "infrastructure"  # requested class, numeric override preserved
        assert response.headers["X-AI-Gateway-Priority"] == "73"
        assert response.headers["X-AI-Request-Id"] == job["request_id"]
        assert response.headers["X-AI-Job-Id"] == job["job_id"]
        assert job["domain"] == ("wvc" if "ventilation" in path else "shared")
        assert job["state"] == "completed"
        assert_timestamps(job, 5)
        assert "PRIVATE" not in json.dumps(status) + caplog.text


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("failure", ["http", "transport", "cancel", "unexpected", "none"])
@pytest.mark.anyio
async def test_http_terminal_outcomes(stream, failure, caplog):
    async def handler(request):
        if failure == "transport":
            raise httpx.ConnectError("PRIVATE-PROMPT", request=request)
        if failure == "cancel":
            raise asyncio.CancelledError()
        if failure == "unexpected":
            raise RuntimeError("PRIVATE-PROMPT")
        async def chunks():
            yield b'{}'
        return httpx.Response(503 if failure == "http" else 200, content=chunks())
    app = make_app(handler)
    async with api_client(app) as client:
        if failure in {"cancel", "unexpected"}:
            with pytest.raises(asyncio.CancelledError if failure == "cancel" else RuntimeError):
                await client.post("/api/chat", json={"stream": stream})
        else:
            await client.post("/api/chat", json={"stream": stream})
        status = (await client.get("/status")).json()
        assert status["active_count"] == 0
        assert status["recent_jobs"][-1]["state"] == (
            "completed" if failure == "none" else "cancelled" if failure == "cancel" else "failed")
        assert "PRIVATE-PROMPT" not in json.dumps(status) + caplog.text


@pytest.mark.parametrize("failure", ["read", "cancel", "close", "close_cancel"])
@pytest.mark.anyio
async def test_stream_iteration_and_close_cleanup(failure):
    class Stream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b'{}'
            if failure == "read":
                raise httpx.ReadError("private")
            if failure == "cancel":
                raise asyncio.CancelledError()
        async def aclose(self):
            if failure == "close_cancel":
                raise asyncio.CancelledError()
            if failure == "close":
                raise RuntimeError("private")
    app = make_app(lambda request: httpx.Response(200, stream=Stream()))
    async with api_client(app) as client:
        try:
            await client.post("/api/chat", json={"stream": True})
        except (BaseExceptionGroup, httpx.ReadError, RuntimeError, asyncio.CancelledError, AssertionError):
            pass
        status = (await client.get("/status")).json()
        assert status["active_count"] == 0
        assert status["recent_jobs"][-1]["state"] == ("cancelled" if failure in {"cancel", "close_cancel"} else "failed")


@pytest.mark.anyio
async def test_invalid_scheduler_transition_keeps_ownership():
    scheduler = PriorityScheduler()
    first = await scheduler.acquire(priority=10, source="first")
    queued = await scheduler.reserve(priority=50, source="queued")
    with pytest.raises(ValueError):
        await scheduler.mark_running(queued.job_id, provider="invalid")
    with pytest.raises(ValueError):
        await scheduler.release_job(queued.job_id, state=State.COMPLETED)
    assert (await scheduler.job_status(queued.job_id))["state"] == "queued"
    await scheduler.release_job(queued.job_id)
    await scheduler.release(first)


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("release", [False, True])
@pytest.mark.parametrize("fail", [False, True])
@pytest.mark.anyio
async def test_leased_http_preserves_reservation_identity_and_ownership(stream, release, fail):
    def handler(request):
        if fail:
            raise httpx.ConnectError("private", request=request)
        async def chunks():
            yield b'{}'
        return httpx.Response(200, content=chunks())
    async with api_client(make_app(handler)) as client:
        lease = (await client.post("/resource/leases", json={"priority_class": "interactive"})).json()
        response = await client.post("/api/chat", json={"stream": stream, "priority_class": "maintenance"}, headers={
            "X-AI-Resource-Lease": lease["lease_id"],
            "X-AI-Resource-Lease-Release": "1" if release else "0",
        })
        assert response.status_code == (502 if fail else 200)
        assert response.headers["X-AI-Job-Id"] == lease["job"]["job_id"]
        assert response.headers["X-AI-Request-Id"] == lease["job"]["request_id"]
        assert response.headers["X-AI-Gateway-Priority"] == "50"
        status = (await client.get("/status")).json()
        assert status["active_count"] == (0 if release else 1)
        if not release:
            job = status["active"][0]["job"]
            assert job["state"] == "admitted"  # reservation, not provider execution
            assert job["priority_class"] == "interactive"
            assert job["assigned_provider"] is None
            await client.delete(f"/resource/leases/{lease['lease_id']}")
        else:
            assert status["recent_jobs"][-1]["state"] == "completed"


@pytest.mark.anyio
async def test_idle_active_expiry_and_in_use_protection(monkeypatch):
    scheduler = PriorityScheduler(max_concurrency=2)
    registry = ResourceLeaseRegistry(scheduler, ttl_seconds=10)
    idle = await registry.create(priority=50, source="idle")
    busy = await registry.create(priority=50, source="busy")
    await registry.begin_use(busy["lease_id"])
    monkeypatch.setattr("ai_bridge.gateway.resource_leases.monotonic", lambda: float("inf"))
    assert await registry.reap_expired() == 1
    assert await scheduler.job_status(idle["job_id"]) is None
    status = await scheduler.snapshot()
    assert status["active_count"] == 1
    assert status["recent_jobs"][-1]["state"] == "expired"
    assert_timestamps(status["recent_jobs"][-1], 4)
    await registry.end_use(busy["lease_id"], release=True)


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.anyio
async def test_client_task_cancellation_releases_running_slot(stream):
    started = asyncio.Event()
    async def handler(request):
        async def chunks():
            started.set()
            await asyncio.Event().wait()
            yield b'{}'
        if stream:
            return httpx.Response(200, content=chunks())
        started.set()
        await asyncio.Event().wait()
    app = make_app(handler)
    async with api_client(app) as client:
        task = asyncio.create_task(client.post("/api/chat", json={"stream": stream}))
        await asyncio.wait_for(started.wait(), 1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        status = (await client.get("/status")).json()
        assert status["active_count"] == status["queued_count"] == 0
        assert status["recent_jobs"][-1]["state"] == "cancelled"


@pytest.mark.anyio
async def test_trusted_metadata_can_correlate_multiple_future_platform_jobs():
    scheduler = PriorityScheduler()
    metadata = JobMetadata(domain="ecu-repair", capability="reasoning", priority_class=PriorityClass.NORMAL)
    for _ in range(2):
        async with scheduler.slot(priority=100, source="internal", metadata=metadata):
            pass
    jobs = (await scheduler.snapshot())["recent_jobs"]
    assert jobs[0]["request_id"] == jobs[1]["request_id"] == metadata.request_id
    assert jobs[0]["job_id"] != jobs[1]["job_id"]
