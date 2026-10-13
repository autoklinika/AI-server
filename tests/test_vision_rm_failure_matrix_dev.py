"""Vision GPU Resource Manager: fail-closed regression matrix, no real GPU.

All /proc and GPU ownership failures are simulated. Persisted block markers
are isolated in tmp_path; NEVER touch a production residency marker.
"""
from __future__ import annotations
import asyncio
from pathlib import Path

import httpx
import pytest

from ai_bridge.gateway.admission import binding, external_workload
from ai_bridge.gateway.jobs import JobMetadata
from ai_bridge.gateway.residency import GPUResidency, ResidencyError
from ai_bridge.gateway.resource_leases import ResourceLeaseRegistry
from ai_bridge.gateway.scheduler import PriorityScheduler
from ai_bridge.providers.registry import local_descriptor_registry
from test_gpu_residency import Providers

@pytest.fixture
def anyio_backend():
    return "asyncio"

def fixture_rm(tmp_path):
    providers=Providers()
    providers.models=[]
    state={"birth":1200,"members":{222}, "vram":12345}
    transport=httpx.MockTransport(providers.handle)
    client=httpx.AsyncClient(base_url="http://mock",transport=transport)
    reg=local_descriptor_registry(enable_vision=True)
    gpu=GPUResidency(
        client,client,tmp_path/"DEV_only_recovery_marker",
        vision_process_probe=lambda pid: state["birth"] if pid==222 else None,
        vision_scope_probe=lambda pid:"test-scope" if pid==222 else None,
        vision_cgroup_members=lambda scope:state["members"] if scope=="test-scope" else None,
        vision_memory_probe=lambda:state["vram"],
        timeout=.5,poll=.001,
    )
    scheduler=PriorityScheduler(max_concurrency=4,registry=reg)
    leases=ResourceLeaseRegistry(scheduler,ttl_seconds=.01,residency=gpu,vision_enabled=True)
    return providers,state,client,gpu,scheduler,leases,reg

async def admit(leases,reg):
    lease=await leases.create(priority=200,source="vision-dev-fault-injection",
                             metadata=JobMetadata(workload=external_workload(reg,"vision-benchmark")))
    work=binding(reg,"vision-local","image-analysis")
    use=await leases.begin_external_use(lease["lease_id"],work,worker_pid=222,scope_path="test-scope")
    return lease,use

@pytest.mark.anyio
@pytest.mark.parametrize("fault",[
    "worker-still-alive", "pid-reused", "orphan-cgroup-child",
    "unknown-cgroup-members", "vram-leak", "vram-inaccessible",
    "ollama-reloaded", "comfy-busy", "comfy-resident",
])
async def test_vision_gpu_cleanup_faults_retain_marker_and_shared_queue(tmp_path,fault):
    providers,state,client,gpu,scheduler,leases,reg=fixture_rm(tmp_path)
    try:
        lease,use=await admit(leases,reg)
        assert gpu.state=="vision" and gpu.marker.is_file()
        state.update(birth=None,members=set())
        if fault=="worker-still-alive":state.update(birth=1200,members={222})
        elif fault=="pid-reused":state.update(birth=6789,members={222})
        elif fault=="orphan-cgroup-child":state["members"]={333}
        elif fault=="unknown-cgroup-members":state["members"]=None
        elif fault=="vram-leak":state["vram"]+=65*1024*1024
        elif fault=="vram-inaccessible":state["vram"]=None
        elif fault=="ollama-reloaded":providers.models=[{"name":"unmanaged"}]
        elif fault=="comfy-busy":providers.busy=True
        elif fault=="comfy-resident":providers.loaded_models=1
        with pytest.raises((ResidencyError,Exception)):
            await leases.end_external_use(lease["lease_id"],use)
        assert scheduler.admission_blocked and gpu.state=="blocked"
        assert gpu.marker.is_file()
        # Releasing owner lease cannot falsely reopen GPU after failed cleanup.
        await leases.release(lease["lease_id"])
        assert (await scheduler.snapshot())["active_count"]==1
        reservation=await scheduler.reserve(priority=10,source="WVC-next")
        assert (await scheduler.job_status(reservation.job_id))["state"]=="queued"
        assert GPUResidency(client,client,gpu.marker).state=="blocked"
        await leases.release(lease["lease_id"])
        await scheduler.release_job(reservation.job_id)
    finally:
        await client.aclose()

@pytest.mark.anyio
@pytest.mark.parametrize("fault",["comfy-busy-before","missing-comfy-residency","worker-exited","pid-reuse"])
async def test_vision_admission_fault_never_issues_valid_use_token(tmp_path,fault):
    providers,state,client,gpu,scheduler,leases,reg=fixture_rm(tmp_path)
    if fault=="comfy-busy-before":providers.busy=True
    if fault=="missing-comfy-residency":
        # Keep same client with transport but simulate not-ready/incorrect evidence.
        providers.loaded_models=1
    if fault=="worker-exited":state["birth"]=None
    if fault=="pid-reuse":
        tick=[1200,4321]
        gpu.vision_process_probe=lambda pid:tick.pop(0)
    try:
        lease=await leases.create(priority=200,source="vision",metadata=JobMetadata(
            workload=external_workload(reg,"vision-benchmark")))
        with pytest.raises(Exception):
            await leases.begin_external_use(lease["lease_id"],
                binding(reg,"vision-local","image-analysis"),worker_pid=222,scope_path="test-scope")
        status=await leases.snapshot()
        if fault=="worker-exited":
            # Rejected before GPU dirty marker write; no GPU was admitted.
            assert gpu.state=="llm" and not gpu.marker.exists()
            await leases.release(lease["lease_id"])
            assert (await scheduler.snapshot())["active_count"]==0
        else:
            assert status["lease_count"]==1
            assert scheduler.admission_blocked and gpu.state=="blocked"
            assert gpu.marker.is_file()
            await leases.release(lease["lease_id"])
            assert (await scheduler.snapshot())["active_count"]==1
    finally:
        await client.aclose()

@pytest.mark.anyio
async def test_active_external_vision_lease_never_reaped_if_worker_heartbeat_missing(tmp_path):
    providers,state,client,gpu,scheduler,leases,reg=fixture_rm(tmp_path)
    try:
        lease,use=await admit(leases,reg)
        await asyncio.sleep(.035)  # TTL only applies to IDLE leases
        assert await leases.reap_expired()==0
        assert (await scheduler.snapshot())["active_count"]==1
        assert gpu.state=="vision" and gpu.marker.is_file()
        # Forced restart observes persistent marker: fail-closed.
        assert GPUResidency(client,client,gpu.marker).snapshot()["recovery_required"]
        state.update(birth=None,members=set())
        assert await leases.end_external_use(lease["lease_id"],use)
        await leases.release(lease["lease_id"])
    finally:
        await client.aclose()

@pytest.mark.anyio
async def test_pid_disappears_after_preflight_but_before_residency_creates_marker(tmp_path):
    """Regression: admitted use must persist marker even on early PID race."""
    providers,state,client,gpu,scheduler,leases,reg=fixture_rm(tmp_path)
    values=iter((1200,None))
    gpu.vision_process_probe=lambda pid:next(values)
    try:
        lease=await leases.create(priority=200,source="vision-race",metadata=JobMetadata(
            workload=external_workload(reg,"vision-benchmark")))
        with pytest.raises(Exception):
            await leases.begin_external_use(lease["lease_id"],
                binding(reg,"vision-local","image-analysis"),worker_pid=222,scope_path="test-scope")
        # Preflight passed and GPU ownership got pinned, so marker MUST exist.
        assert scheduler.admission_blocked
        assert gpu.state=="blocked" and gpu.marker.is_file()
        await leases.release(lease["lease_id"])
        assert (await scheduler.snapshot())["active_count"]==1
        assert GPUResidency(client,client,gpu.marker).state=="blocked"
    finally:
        await client.aclose()


@pytest.mark.anyio
async def test_recovery_marker_stops_fresh_gateway_after_worker_cleanup_failed(tmp_path):
    """A new Gateway with the same marker must not admit WVC or Vision."""
    from ai_bridge.gateway.app import create_gateway_app
    from ai_bridge.settings import Settings
    from test_gateway_priority_classes import api_client
    providers,state,client,gpu,scheduler,leases,reg=fixture_rm(tmp_path)
    try:
        lease,use=await admit(leases,reg)
        state.update(birth=None,members=set(),vram=12345+80*1024*1024)
        with pytest.raises(Exception):
            await leases.end_external_use(lease["lease_id"],use)
        assert gpu.marker.exists()
        app=create_gateway_app(Settings(
            _env_file=None,gateway_vision_external_enabled=True,
            gateway_gpu_marker=gpu.marker),
            upstream_transport=httpx.MockTransport(providers.handle),
            residency_transport=httpx.MockTransport(providers.handle))
        async with api_client(app) as fresh:
            health=(await fresh.get('/health')).json()
            assert health['status']=='degraded'
            lease2=(await fresh.post('/resource/leases',json={'workload':'vision-benchmark'})).json()
            assert lease2['state']=='queued'
            wvc=(await fresh.post('/resource/leases',json={'workload':'llm'})).json()
            assert wvc['state']=='queued'
            status=(await fresh.get('/status')).json()
            assert status['gpu_residency']['recovery_required']
            assert status['active_count']==0 and status['queued_count']==2
            await fresh.delete('/resource/leases/'+lease2['lease_id'])
            await fresh.delete('/resource/leases/'+wvc['lease_id'])
    finally:
        await client.aclose()
