"""DEV-only Vision GPU provider tests against the existing, shared RM.

No real GPU or external processes are needed. Production default remains OFF.
"""
import asyncio

import httpx
import pytest

from ai_bridge.gateway.app import create_gateway_app
from ai_bridge.gateway.admission import binding, external_workload
from ai_bridge.gateway.resource_leases import ResourceLeaseRegistry, ResourceLeaseNotActive
from ai_bridge.gateway.residency import GPUResidency
from ai_bridge.gateway.scheduler import PriorityScheduler
from ai_bridge.providers.registry import local_descriptor_registry
from ai_bridge.settings import Settings
from test_gateway_priority_classes import api_client
from test_gpu_residency import Providers


@pytest.fixture
def anyio_backend():
    return "asyncio"


def test_default_inventory_and_vision_profile_fail_closed():
    legacy = local_descriptor_registry("local-test")
    assert [p.provider_id for p in legacy.providers] == [
        "ollama-local", "comfyui-local", "hermes-local"
    ]
    legacy.validate_local_gateway("local-test")
    with pytest.raises(ValueError):
        external_workload(legacy, "vision-benchmark")
    extended = local_descriptor_registry("local-test", enable_vision=True)
    extended.validate_local_gateway("local-test", enable_vision=True)
    assert external_workload(extended, "vision-benchmark")[0].provider == "vision-local"
    with pytest.raises(ValueError):
        extended.validate_local_gateway("local-test")  # requires explicit opt-in


@pytest.mark.anyio
async def test_gateway_rejects_vision_without_opt_in(tmp_path):
    app = create_gateway_app(
        Settings(_env_file=None, gateway_gpu_marker=tmp_path/"not-enabled"),
        upstream_transport=httpx.MockTransport(Providers().handle),
        residency_transport=httpx.MockTransport(Providers().handle),
    )
    async with api_client(app) as client:
        assert (await client.post("/resource/leases", json={"workload":"vision-benchmark"})).status_code == 400
        legacy=(await client.post("/resource/leases", json={"workload":"external"})).json()
        use=await client.post(f"/resource/leases/{legacy['lease_id']}/uses", json={
            "provider":"vision-local","capability":"image-analysis","worker_pid":222,"scope_path":"fake-scope"})
        assert use.status_code == 400
        await client.delete(f"/resource/leases/{legacy['lease_id']}")
        assert (await client.get("/status")).json()["resource_leases"]["lease_count"] == 0


@pytest.mark.anyio
async def test_vision_lease_reuses_shared_scheduler_and_cleanup(tmp_path):
    providers=Providers()
    state={"worker_birth":999,"vram":1024}
    app=create_gateway_app(
        Settings(_env_file=None, gateway_vision_external_enabled=True,
                 gateway_gpu_marker=tmp_path/"vision-marker"),
        upstream_transport=httpx.MockTransport(providers.handle),
        residency_transport=httpx.MockTransport(providers.handle),
    )
    async with api_client(app) as client:
        residency=app.state.resource_leases.residency
        residency.vision_process_probe=lambda pid: state["worker_birth"] if pid==222 else None
        residency.vision_memory_probe=lambda:state["vram"]
        residency.vision_scope_probe=lambda pid:"fake-scope"
        residency.vision_cgroup_members=lambda path:({222} if state["worker_birth"] else set())
        blockers=app.state.scheduler
        in_flight=await blockers.acquire(priority=25,source="wvc-simulation")
        lease=(await client.post("/resource/leases",json={
            "source":"vision-benchmark","workload":"vision-benchmark",
            "priority_class":"background"})).json()
        assert lease["state"]=="queued"
        await blockers.release(in_flight)
        lid=lease["lease_id"]
        assert (await client.get(f"/resource/leases/{lid}")).json()["state"]=="active"
        endpoint=f"/resource/leases/{lid}/uses"
        payload={"provider":"vision-local","capability":"image-analysis","worker_pid":222,"scope_path":"fake-scope"}
        response=await client.post(endpoint,json=payload)
        assert response.status_code==201, response.text
        uid=response.json()["use_id"]
        assert providers.models==[]
        assert residency.state=="vision" and residency.marker.exists()
        assert (await client.get(endpoint+f"/{uid}")).json()["provider"]=="vision-local"
        assert (await client.post(endpoint,json=payload)).status_code==409
        # Worker must finish BEFORE release; owning process cannot be trusted to claim cleanup.
        state["worker_birth"]=None
        cleanup=await client.delete(endpoint+f"/{uid}")
        assert cleanup.status_code==200
        assert cleanup.json()=={"released":True}
        assert residency.state=="llm" and not residency.marker.exists()
        assert (await client.get(endpoint+f"/{uid}")).status_code==409
        await client.delete(f"/resource/leases/{lid}")
        status=(await client.get("/status")).json()
        assert status["resource_leases"]["lease_count"]==0
        assert status["active_count"]==0


@pytest.mark.anyio
@pytest.mark.parametrize("failure",["worker_still_alive","gpu_memory_leak","missing_memory_evidence"])
async def test_vision_cleanup_failure_blocks_shared_gpu(tmp_path,failure):
    providers=Providers()
    state={"birth":777,"vram":1000}
    client=httpx.AsyncClient(base_url="http://provider",transport=httpx.MockTransport(providers.handle))
    registry=local_descriptor_registry(enable_vision=True)
    gpu=GPUResidency(client,client,tmp_path/"blocked-marker",
                     vision_process_probe=lambda pid:state["birth"],
                     vision_memory_probe=lambda:state["vram"],
                     vision_scope_probe=lambda pid:"fake-scope",
                     vision_cgroup_members=lambda path:({222} if state["birth"] else set()),
                     timeout=.06,poll=.001)
    scheduler=PriorityScheduler(max_concurrency=1,registry=registry)
    leases=ResourceLeaseRegistry(scheduler,residency=gpu,vision_enabled=True)
    lease=await leases.create(priority=200,source="vision",metadata=None)
    # metadata default reserves legacy providers, so use explicit descriptor plan.
    await leases.release(lease["lease_id"])
    from ai_bridge.gateway.jobs import JobMetadata
    lease=await leases.create(priority=200,source="vision",metadata=JobMetadata(
        workload=external_workload(registry,"vision-benchmark")))
    use=await leases.begin_external_use(lease["lease_id"],binding(registry,"vision-local","image-analysis"),worker_pid=222,scope_path="fake-scope")
    if failure=="worker_still_alive":
        pass
    elif failure=="gpu_memory_leak":
        state.update(birth=None,vram=1000+65*1024*1024)
    else:
        state.update(birth=None,vram=None)
    with pytest.raises(Exception):
        await leases.end_external_use(lease["lease_id"],use)
    assert scheduler.admission_blocked
    assert gpu.marker.exists() and gpu.state=="blocked"
    await leases.release(lease["lease_id"])
    assert (await scheduler.snapshot())["active_count"]==1
    # On service restart persistent marker keeps admission closed.
    restarted=GPUResidency(client,client,gpu.marker)
    assert restarted.state=="blocked"
    await client.aclose()


@pytest.mark.anyio
async def test_vision_rejects_missing_worker_pid_before_transition(tmp_path):
    registry=local_descriptor_registry(enable_vision=True)
    scheduler=PriorityScheduler(registry=registry)
    leases=ResourceLeaseRegistry(scheduler,vision_enabled=True)
    from ai_bridge.gateway.jobs import JobMetadata
    lease=await leases.create(priority=200,source="vision",metadata=JobMetadata(
        workload=external_workload(registry,"vision-benchmark")))
    bind=binding(registry,"vision-local","image-analysis")
    with pytest.raises(Exception):
        await leases.begin_external_use(lease["lease_id"],bind)
    await leases.release(lease["lease_id"])
    assert (await scheduler.snapshot())["active_count"]==0

@pytest.mark.anyio
async def test_worker_pid_reuse_before_admission_blocks_gpu(tmp_path):
    providers = Providers()
    client = httpx.AsyncClient(base_url='http://test', transport=httpx.MockTransport(providers.handle))
    identities = iter([12345, 23456])
    gpu = GPUResidency(client, client, tmp_path/'vision-dirty',
                       vision_process_probe=lambda pid: next(identities),
                       vision_memory_probe=lambda: 1024,
                       vision_scope_probe=lambda pid:"fake-scope",
                       vision_cgroup_members=lambda path:{222},timeout=.6,poll=.001)
    with pytest.raises(Exception, match='identity changed'):
        await gpu.enter_vision(222,"fake-scope")
    assert gpu.state == 'blocked' and gpu.marker.exists()
    await client.aclose()


@pytest.mark.anyio
async def test_vision_baseline_measured_after_ollama_unload(tmp_path):
    providers = Providers()
    states = {'birth':999, 'vram':200000000}
    def handler(request):
        result = providers.handle(request)
        if request.url.path == '/api/generate':
            states['vram'] = 50000000
        return result
    client = httpx.AsyncClient(base_url='http://test', transport=httpx.MockTransport(handler))
    gpu = GPUResidency(client,client,tmp_path/'marker',
                       vision_process_probe=lambda pid: states['birth'],
                       vision_memory_probe=lambda: states['vram'],
                       vision_scope_probe=lambda pid:"fake-scope",
                       vision_cgroup_members=lambda path:({222} if states["birth"] else set()),
                       timeout=.6,poll=.001)
    await gpu.enter_vision(222,"fake-scope")
    assert gpu._vision_baseline_bytes == 50000000
    states.update(birth=None,vram=50000000)
    await gpu.leave_vision()
    assert gpu.state == 'llm' and not gpu.marker.exists()
    await client.aclose()


def test_proc_reader_existing_process_and_invalid_pid():
    import os
    from ai_bridge.gateway.vision_residency_evidence import worker_birth_ticks
    assert worker_birth_ticks(os.getpid()) is not None
    assert worker_birth_ticks(os.getpid()) > 0
    assert worker_birth_ticks(-1) is None
    assert worker_birth_ticks(True) is None

@pytest.mark.anyio
async def test_vision_drain_is_exclusive_at_max_concurrency_four():
    from ai_bridge.gateway.jobs import JobMetadata
    registry=local_descriptor_registry(enable_vision=True)
    scheduler=PriorityScheduler(max_concurrency=4,registry=registry)
    normal=await scheduler.acquire(priority=50,source='llm',metadata=JobMetadata(
        workload=external_workload(registry,'llm')))
    vision=await scheduler.reserve(priority=200,source='vision',metadata=JobMetadata(
        workload=external_workload(registry,'vision-benchmark')))
    assert (await scheduler.job_status(vision.job_id))['state']=='queued'
    await scheduler.release(normal)
    assert (await scheduler.job_status(vision.job_id))['state']=='active'
    waiting=asyncio.create_task(scheduler.acquire(priority=10,source='WVC',metadata=JobMetadata(
        workload=external_workload(registry,'llm'))))
    await asyncio.sleep(0)
    assert not waiting.done()
    assert (await scheduler.snapshot())['active_count']==1
    await scheduler.release_job(vision.job_id)
    ticket=await asyncio.wait_for(waiting,1)
    await scheduler.release(ticket)


@pytest.mark.anyio
async def test_two_vision_reservations_do_not_overlap():
    from ai_bridge.gateway.jobs import JobMetadata
    registry=local_descriptor_registry(enable_vision=True)
    scheduler=PriorityScheduler(max_concurrency=4,registry=registry)
    meta=JobMetadata(workload=external_workload(registry,'vision-benchmark'))
    first=await scheduler.reserve(priority=200,source='vision-1',metadata=meta)
    second=await scheduler.reserve(priority=200,source='vision-2',metadata=meta)
    assert (await scheduler.job_status(first.job_id))['state']=='active'
    assert (await scheduler.job_status(second.job_id))['state']=='queued'
    await scheduler.release_job(first.job_id)
    assert (await scheduler.job_status(second.job_id))['state']=='active'
    await scheduler.release_job(second.job_id)
    assert (await scheduler.snapshot())['active_count']==0


@pytest.mark.anyio
async def test_orphaned_cgroup_child_blocks_cleanup(tmp_path):
    providers = Providers()
    state = {'birth':123,'members':{222},'vram':1000}
    client = httpx.AsyncClient(base_url='http://test',transport=httpx.MockTransport(providers.handle))
    gpu = GPUResidency(client,client,tmp_path/'dirty',timeout=.6,poll=.001,
            vision_process_probe=lambda pid:state['birth'],
            vision_memory_probe=lambda:state['vram'],
            vision_scope_probe=lambda pid:'fake-scope',
            vision_cgroup_members=lambda scope:state['members'])
    await gpu.enter_vision(222,'fake-scope')
    state.update(birth=None,members={333})  # detached descendant survived parent
    with pytest.raises(Exception,match='cgroup not empty'):
        await gpu.leave_vision()
    assert gpu.state=='blocked' and gpu.marker.exists()
    await client.aclose()
