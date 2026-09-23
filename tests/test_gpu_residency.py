import asyncio
import json

import httpx
import pytest

from ai_bridge.gateway.admission import binding, external_workload
from ai_bridge.gateway.jobs import JobMetadata
from ai_bridge.gateway.residency import GPUResidency
from ai_bridge.gateway.resource_leases import ResourceLeaseRegistry, ResourceLeaseNotActive
from ai_bridge.gateway.scheduler import PriorityScheduler


@pytest.fixture
def anyio_backend():
    return "asyncio"


class Providers:
    def __init__(self):
        self.models = [{"name": "resident"}]
        self.memory = 1024
        self.calls = []
        self.fail = False
        self.stuck = False
        self.busy = False

    def handle(self, request):
        path = request.url.path
        self.calls.append(path)
        if self.fail:
            return httpx.Response(500)
        if path == "/api/ps":
            return httpx.Response(200, json={"models": self.models})
        if path == "/api/generate":
            assert json.loads(request.content) == {"model": "resident", "keep_alive": 0, "stream": False}
            if not self.stuck:
                self.models = []
        if path == "/queue":
            return httpx.Response(200, json={"queue_running": [1] if self.busy else [], "queue_pending": []})
        if path == "/free" and not self.stuck:
            self.memory = 0
        if path == "/system_stats":
            return httpx.Response(200, json={"devices": [{"torch_vram_total": self.memory}]})
        return httpx.Response(200, json={})


def setup(tmp_path, providers):
    client = httpx.AsyncClient(base_url="http://test", transport=httpx.MockTransport(providers.handle))
    gpu = GPUResidency(client, client, tmp_path / "gpu.blocked", timeout=.05, poll=.001)
    scheduler = PriorityScheduler(max_concurrency=4)
    leases = ResourceLeaseRegistry(scheduler, ttl_seconds=.001, residency=gpu)
    return gpu, scheduler, leases


@pytest.mark.anyio
async def test_drain_residency_cleanup_and_queue_order(tmp_path):
    providers = Providers()
    gpu, scheduler, leases = setup(tmp_path, providers)
    llm = await scheduler.acquire(priority=50, source="active")
    lease = await leases.create(priority=50, source="media", metadata=JobMetadata(workload=external_workload(scheduler.registry, "media-image")))
    assert lease["state"] == "queued"
    waiting = asyncio.create_task(scheduler.acquire(priority=100, source="next"))
    await asyncio.sleep(0)
    assert not waiting.done()
    await scheduler.release(llm)
    work = binding(scheduler.registry, "comfyui-local", "image-generation")
    use = await leases.begin_external_use(lease["lease_id"], work)
    assert providers.models == [] and providers.calls.count("/api/ps") >= 2
    assert gpu.state == "media" and gpu.marker.exists()
    assert not waiting.done()
    with pytest.raises(ResourceLeaseNotActive):
        await leases.begin_use(lease["lease_id"])
    await leases.release(lease["lease_id"])
    await asyncio.sleep(.002)
    assert await leases.reap_expired() == 0
    assert not waiting.done()
    await leases.end_external_use(lease["lease_id"], use)
    assert providers.memory == 0 and gpu.state == "llm" and not gpu.marker.exists()
    ticket = await asyncio.wait_for(waiting, 1)
    assert not await leases.end_external_use(lease["lease_id"], use)
    await scheduler.release(ticket)


@pytest.mark.anyio
@pytest.mark.parametrize("failure", ["unload_http", "unload_timeout", "cleanup_http", "cleanup_timeout", "busy"])
async def test_failure_retains_ownership_and_restart_marker(tmp_path, failure):
    providers = Providers()
    gpu, scheduler, leases = setup(tmp_path, providers)
    lease = await leases.create(priority=50, source="media")
    work = binding(scheduler.registry, "comfyui-local", "video-generation")
    if failure.startswith("unload"):
        providers.fail = failure == "unload_http"
        providers.stuck = failure == "unload_timeout"
        with pytest.raises(Exception):
            await leases.begin_external_use(lease["lease_id"], work)
    else:
        use = await leases.begin_external_use(lease["lease_id"], work)
        providers.fail = failure == "cleanup_http"
        providers.stuck = failure == "cleanup_timeout"
        providers.busy = failure == "busy"
        with pytest.raises(Exception):
            await leases.end_external_use(lease["lease_id"], use)
    await leases.release(lease["lease_id"])
    await asyncio.sleep(.002)
    assert await leases.reap_expired() == 0
    assert scheduler.admission_blocked and gpu.state == "blocked"
    assert GPUResidency(gpu.ollama, gpu.comfy, gpu.marker).state == "blocked"
    queued = await scheduler.reserve(priority=1, source="must wait")
    assert (await scheduler.job_status(queued.job_id))["state"] == "queued"


@pytest.mark.anyio
async def test_heartbeat_and_release_during_transition_are_race_safe(tmp_path):
    providers = Providers()
    gpu, scheduler, leases = setup(tmp_path, providers)
    entered, finish = asyncio.Event(), asyncio.Event()
    original = gpu.enter_media
    async def delayed():
        entered.set()
        await finish.wait()
        await original()
    gpu.enter_media = delayed
    lease = await leases.create(priority=50, source="media")
    task = asyncio.create_task(leases.begin_external_use(lease["lease_id"], binding(scheduler.registry, "comfyui-local", "video-generation")))
    await entered.wait()
    await asyncio.wait_for(leases.heartbeat(lease["lease_id"]), .1)
    await leases.release(lease["lease_id"])
    assert (await scheduler.snapshot())["active_count"] == 1
    finish.set()
    use = await task
    await leases.end_external_use(lease["lease_id"], use)
    assert (await scheduler.snapshot())["active_count"] == 0


@pytest.mark.anyio
async def test_cancel_during_unload_keeps_pin_and_marker(tmp_path):
    providers = Providers()
    providers.stuck = True
    gpu, scheduler, leases = setup(tmp_path, providers)
    gpu.timeout = 5
    lease = await leases.create(priority=50, source="media")
    task = asyncio.create_task(leases.begin_external_use(lease['lease_id'], binding(scheduler.registry, 'comfyui-local', 'video-generation')))
    while not gpu.marker.exists():
        await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await leases.release(lease['lease_id'])
    assert gpu.marker.exists() and scheduler.admission_blocked
    assert (await scheduler.snapshot())['active_count'] == 1


@pytest.mark.anyio
async def test_http_external_use_runs_real_transition_and_repeated_cleanup(tmp_path):
    from test_gateway_unified_admission import media_app
    from test_gateway_priority_classes import api_client
    async with api_client(media_app(tmp_path)) as client:
        lease = (await client.post('/resource/leases', json={'workload': 'media-image'})).json()
        path = f"/resource/leases/{lease['lease_id']}/uses"
        use = (await client.post(path, json={'provider': 'comfyui-local', 'capability': 'image-generation'})).json()
        assert (await client.get('/status')).json()['gpu_residency']['state'] == 'media'
        for _ in range(2):
            response = await client.delete(path + '/' + use['use_id'])
            assert response.status_code == 200 and response.json()['released']
        assert (await client.get('/status')).json()['gpu_residency']['state'] == 'llm'
        await client.delete(f"/resource/leases/{lease['lease_id']}")


@pytest.mark.anyio
async def test_restart_marker_degrades_health_and_keeps_requests_queued(tmp_path):
    from test_gateway_priority_classes import api_client, make_app
    marker = tmp_path / 'dirty'
    marker.write_text('uncertain GPU ownership')
    app = make_app(gateway_gpu_marker=marker)
    async with api_client(app) as client:
        assert (await client.get('/health')).json()['status'] == 'degraded'
        lease = (await client.post('/resource/leases', json={'workload': 'llm'})).json()
        assert lease['state'] == 'queued'
        assert (await client.get('/status')).json()['gpu_residency']['recovery_required']
        await client.delete(f"/resource/leases/{lease['lease_id']}")


@pytest.mark.anyio
@pytest.mark.parametrize('memory,success', [(33554432, True), (33554433, False)])
async def test_only_explicit_bounded_workspace_survives_cleanup(tmp_path, memory, success):
    providers = Providers()
    gpu, scheduler, leases = setup(tmp_path, providers)
    gpu.idle_reserve_bytes = 33554432
    await gpu.enter_media()
    providers.memory, providers.stuck = memory, True
    if success:
        await gpu.leave_media()
        assert gpu.state == 'llm'
    else:
        with pytest.raises(TimeoutError):
            await gpu.leave_media()
        assert gpu.state == 'blocked'


@pytest.mark.anyio
async def test_unmanaged_ollama_reload_prevents_reopening(tmp_path):
    providers = Providers()
    gpu, scheduler, leases = setup(tmp_path, providers)
    await gpu.enter_media()
    providers.models = [{'name': 'rogue-preload'}]
    with pytest.raises(Exception, match='reloaded outside'):
        await gpu.leave_media()
    assert gpu.state == 'blocked' and gpu.marker.exists()


@pytest.mark.anyio
async def test_renderer_token_is_only_valid_during_owned_media_phase(tmp_path):
    from test_gateway_unified_admission import media_app
    from test_gateway_priority_classes import api_client
    async with api_client(media_app(tmp_path)) as client:
        lease = (await client.post('/resource/leases', json={'workload': 'media-image'})).json()
        path = f"/resource/leases/{lease['lease_id']}/uses"
        assert (await client.get(path + '/unknown')).status_code == 409
        use = (await client.post(path, json={'provider': 'comfyui-local', 'capability': 'image-generation'})).json()['use_id']
        assert (await client.get(path + '/' + use)).json() == {'provider': 'comfyui-local', 'capability': 'image-generation'}
        await client.delete(path + '/' + use)
        assert (await client.get(path + '/' + use)).status_code == 409
        await client.delete(f"/resource/leases/{lease['lease_id']}")
