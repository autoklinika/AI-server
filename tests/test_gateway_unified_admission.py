"""D.4 admission integration: all transports contend for the same reservation."""
import asyncio
import json

import httpx
import pytest

from ai_bridge.gateway.admission import WorkloadBinding, binding, external_workload, http_workload
from ai_bridge.gateway.jobs import JobMetadata
from ai_bridge.gateway.resource_leases import ResourceLeaseNotActive, ResourceLeaseRegistry
from ai_bridge.gateway.scheduler import PriorityScheduler
from test_gateway_priority_classes import PATHS, api_client, make_app


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.parametrize("profile", ["external", "llm", "embeddings", "media-image", "media-video"])
@pytest.mark.anyio
async def test_profiles_share_job_model_and_descriptors(profile):
    app = make_app(node_id="local-test")
    async with api_client(app) as client:
        lease = (await client.post("/resource/leases", json={"workload": profile})).json()
        expected = external_workload(app.state.descriptor_registry, profile)
        job = lease["job"]
        assert job["workload"] == [dict(provider=item.provider, node=item.node, capability=item.capability) for item in expected]
        assert job["state"] == "admitted"
        assert job["assigned_provider"] is None
        status = (await client.get("/status")).json()
        assert status["active"][0]["job"] == status["resource_leases"]["leases"][0]["job"] == job
        await client.delete(f"/resource/leases/{lease['lease_id']}")
        final = (await client.get("/status")).json()["recent_jobs"][-1]
        assert final["workload"] == job["workload"]
        assert final["state"] == "completed"


@pytest.mark.parametrize("profile", [None, "", "secret prompt", [], {}, 1, True])
@pytest.mark.anyio
async def test_invalid_profile_fails_before_admission_without_echo(profile):
    async with api_client(make_app()) as client:
        result = await client.post("/resource/leases", json={"workload": profile})
        assert result.status_code == 400
        assert result.json() == {"detail": "invalid workload"}
        status = (await client.get("/status")).json()
        assert not status["recent_jobs"] and status["active_count"] == 0


@pytest.mark.parametrize("path", PATHS)
@pytest.mark.anyio
async def test_http_routes_have_validated_workloads(path):
    app = make_app()
    async with api_client(app) as client:
        result = await client.post(path, json={"prompt": "private content"})
        assert result.status_code == 200
        status = (await client.get("/status")).json()
        job = status["recent_jobs"][-1]
        assert job["workload"] == [{"provider": "ollama-local", "node": "ai-node-01", "capability": job["capability"]}]
        assert "private content" not in json.dumps(status)


@pytest.mark.anyio
async def test_media_qwen_external_phase_and_embedding_contend_without_second_slot(caplog):
    seen = []
    app = make_app(lambda request: seen.append(request.url.path) or httpx.Response(200, json={}))
    async with api_client(app) as client:
        lease = (await client.post("/resource/leases", json={"workload": "media-video", "priority_class": "interactive"})).json()
        lid = lease["lease_id"]
        headers = {"X-AI-Resource-Lease": lid}
        qwen = await client.post("/api/chat", headers=headers, json={"prompt": "private content"})
        assert qwen.headers["x-ai-job-id"] == lease["job"]["job_id"]
        use = await client.post(f"/resource/leases/{lid}/uses", json={"provider": "comfyui-local", "capability": "video-generation"})
        assert use.status_code == 201
        assert (await client.post("/api/chat", headers=headers, json={})).status_code == 409
        assert (await client.post(f"/resource/leases/{lid}/uses", json={"provider": "comfyui-local", "capability": "video-generation"})).status_code == 409
        embedding = asyncio.create_task(client.post("/api/embed", json={"input": "private content"}))
        await asyncio.sleep(0)
        snapshot = (await client.get("/status")).json()
        assert snapshot["active_count"] == snapshot["queued_count"] == 1
        assert snapshot["resource_leases"]["leases"][0]["external_in_use"] is True
        assert snapshot["active"][0]["job"]["assigned_provider"] is None
        assert seen == ["/api/chat"]
        assert "private content" not in json.dumps(snapshot) + caplog.text
        await client.delete(f"/resource/leases/{lid}/uses/{use.json()['use_id']}")
        # Ending a phase never frees the worker's reservation.
        assert not embedding.done()
        await client.delete(f"/resource/leases/{lid}")
        assert (await asyncio.wait_for(embedding, 1)).status_code == 200
        assert seen == ["/api/chat", "/api/embed"]


@pytest.mark.anyio
async def test_restricted_lease_rejects_unplanned_work_and_old_use_cannot_end_new_phase():
    app = make_app()
    async with api_client(app) as client:
        lease = (await client.post("/resource/leases", json={"workload": "media-video"})).json()
        lid = lease["lease_id"]
        assert (await client.post("/api/embed", headers={"X-AI-Resource-Lease": lid}, json={})).status_code == 409
        assert (await client.post(f"/resource/leases/{lid}/uses", json={"provider": "comfyui-local", "capability": "image-edit"})).status_code == 409
        payload = {"provider": "comfyui-local", "capability": "video-generation"}
        first = (await client.post(f"/resource/leases/{lid}/uses", json=payload)).json()["use_id"]
        await client.delete(f"/resource/leases/{lid}/uses/{first}")
        second = (await client.post(f"/resource/leases/{lid}/uses", json=payload)).json()["use_id"]
        assert first != second
        assert not (await client.delete(f"/resource/leases/{lid}/uses/{first}")).json()["released"]
        assert (await client.post("/api/chat", headers={"X-AI-Resource-Lease": lid}, json={})).status_code == 409
        await client.delete(f"/resource/leases/{lid}")


@pytest.mark.parametrize("payload", [{}, {"provider": "hermes-local", "capability": "reasoning"}, {"provider": "comfyui-local", "capability": "secret prompt"}, {"provider": "comfyui-local", "capability": []}, []])
@pytest.mark.anyio
async def test_invalid_external_execution_payload_is_private(payload):
    async with api_client(make_app()) as client:
        response = await client.post("/resource/leases/missing/uses", json=payload)
        assert response.status_code == 400
        assert response.json() == {"detail": "invalid external workload"}


@pytest.mark.anyio
async def test_crashed_external_phase_ttl_and_http_pin_are_distinct(monkeypatch):
    now = [100.0]
    monkeypatch.setattr("ai_bridge.gateway.resource_leases.monotonic", lambda: now[0])
    scheduler = PriorityScheduler()
    leases = ResourceLeaseRegistry(scheduler, ttl_seconds=10)
    lease = await leases.create(priority=50, source="media")
    work = binding(scheduler.registry, "comfyui-local", "video-generation")
    await leases.begin_external_use(lease["lease_id"], work)
    now[0] = 109
    await leases.heartbeat(lease["lease_id"])
    now[0] = 115
    assert await leases.reap_expired() == 0
    now[0] = 120
    assert await leases.reap_expired() == 1
    assert (await scheduler.snapshot())["recent_jobs"][-1]["state"] == "expired"
    lease = await leases.create(priority=50, source="http")
    await leases.begin_use(lease["lease_id"])
    now[0] += 100
    assert await leases.reap_expired() == 0
    await leases.end_use(lease["lease_id"], release=True)
    assert (await scheduler.snapshot())["active_count"] == 0


@pytest.mark.anyio
async def test_queued_external_claim_and_queue_limit_preserved():
    scheduler = PriorityScheduler(max_queue_size=1)
    leases = ResourceLeaseRegistry(scheduler)
    first = await leases.create(priority=50, source="media")
    queued = await leases.create(priority=10, source="wvc")
    with pytest.raises(ResourceLeaseNotActive):
        await leases.begin_external_use(queued["lease_id"], binding(scheduler.registry, "comfyui-local", "video-generation"))
    from ai_bridge.gateway.scheduler import SchedulerQueueFull
    with pytest.raises(SchedulerQueueFull):
        await leases.create(priority=100, source="embedding")
    await leases.release(queued["lease_id"])
    await leases.release(first["lease_id"])
    assert (await scheduler.snapshot())["active_count"] == 0


@pytest.mark.anyio
async def test_cancel_create_while_registry_locked_has_no_orphan():
    scheduler = PriorityScheduler()
    leases = ResourceLeaseRegistry(scheduler)
    async with leases._lock:
        task = asyncio.create_task(leases.create(priority=50, source="media"))
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert (await scheduler.snapshot())["active_count"] == 0
    assert (await leases.snapshot())["lease_count"] == 0


@pytest.mark.anyio
async def test_invalid_workload_binding_rejected_atomically_before_enqueue():
    scheduler = PriorityScheduler()
    for invalid in [WorkloadBinding("comfyui-local", "ai-node-01", "chat"), WorkloadBinding("ollama-local", "other", "chat")]:
        with pytest.raises(ValueError):
            await scheduler.acquire(priority=50, source="test", metadata=JobMetadata(capability="chat", workload=(invalid,)))
    snapshot = await scheduler.snapshot()
    assert snapshot["active_count"] == 0 and not snapshot["recent_jobs"]
    with pytest.raises(ValueError):
        http_workload(scheduler.registry, "/api/future-expensive")


@pytest.mark.anyio
async def test_overlapping_leased_http_does_not_exceed_admission():
    started, finish = asyncio.Event(), asyncio.Event()
    async def upstream(request):
        started.set()
        await finish.wait()
        return httpx.Response(200, json={})
    async with api_client(make_app(upstream)) as client:
        lease = (await client.post("/resource/leases", json={})).json()
        headers = {"X-AI-Resource-Lease": lease["lease_id"]}
        first = asyncio.create_task(client.post("/api/chat", json={}, headers=headers))
        await started.wait()
        assert (await client.post("/api/chat", json={}, headers=headers)).status_code == 409
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        assert (await client.get("/status")).json()["resource_leases"]["leases"][0]["in_use"] == 0
        await client.delete(f"/resource/leases/{lease['lease_id']}")


@pytest.mark.anyio
async def test_direct_proxy_helper_cannot_forward_expensive_route():
    from fastapi import HTTPException
    from starlette.requests import Request
    app = make_app(lambda request: pytest.fail("must not reach upstream"))
    endpoint = next(route.endpoint for route in app.routes if getattr(route, "path", "") == "/api/tags")
    direct = next(cell.cell_contents for cell in endpoint.__closure__ if callable(cell.cell_contents) and cell.cell_contents.__name__ == "proxy_direct")
    request = Request({"type": "http", "method": "POST", "path": "/api/chat", "headers": [], "app": app})
    with pytest.raises(HTTPException) as exc:
        await direct(request, "/api/chat")
    assert exc.value.status_code == 400


@pytest.mark.anyio
async def test_cancel_release_waiting_on_scheduler_keeps_reaper_owner(monkeypatch):
    now = [0.0]
    monkeypatch.setattr("ai_bridge.gateway.resource_leases.monotonic", lambda: now[0])
    scheduler = PriorityScheduler()
    leases = ResourceLeaseRegistry(scheduler, ttl_seconds=10)
    lease = await leases.create(priority=50, source="media")
    async with scheduler._lock:
        task = asyncio.create_task(leases.release(lease["lease_id"]))
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert (await leases.snapshot())["lease_count"] == 1
    now[0] = 11
    assert await leases.reap_expired() == 1
    assert (await scheduler.snapshot())["active_count"] == 0
