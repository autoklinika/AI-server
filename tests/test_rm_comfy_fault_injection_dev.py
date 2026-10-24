"""DEV-only RM fault injection. All workers here are CPU simulated."""
import asyncio
import httpx
import pytest
from ai_bridge.gateway.comfy_ondemand_dev import ServiceIdentity
from test_rm_comfy_ondemand_dev import Controller, MockServices, app, instance

def execute(coroutine):
    return asyncio.run(coroutine)

async def create_lease(client):
    res=await client.post("/resource/leases",
        json={"workload":"media-image","source":"hermes-dev-foto"})
    assert res.status_code==201
    lid=res.json()["lease_id"]
    base=f"/resource/leases/{lid}"
    res=await client.post(base+"/uses",
        json={"provider":"comfyui-local","capability":"image-generation"})
    assert res.status_code==201,res.text
    return base,res.json()["use_id"]

async def assert_fenced(client,ctl):
    h=(await client.get("/health")).json()
    s=(await client.get("/status")).json()
    assert h["status"]=="degraded"
    assert s["admission_blocked"] is True
    assert s["gpu_residency"]["recovery_required"] is True
    assert s["active_count"]==1
    assert ctl.residency.marker.exists()
    return s


@pytest.mark.parametrize("fault",[
    "worker_abnormal_exit","cgroup_memory_exceeded",
    "unresponsive_worker","process_birth_drift","boot_identity_drift",
])
def test_abnormal_worker_never_reopens_rm_admission(tmp_path,fault):
    async def task():
        ctl,svc,server=instance(tmp_path)
        async with server.router.lifespan_context(server):
            ctl.residency=server.state.resource_leases.residency
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=server),
                base_url="http://rm-dev") as client:
                base,useid=await create_lease(client)
                assert ctl.residency.state=="media"
                if fault in ("worker_abnormal_exit","cgroup_memory_exceeded"):
                    ctl.active=False
                elif fault=="boot_identity_drift":
                    old=ctl.current
                    ctl.current=ServiceIdentity(
                        "00000000-0000-0000-0000-000000000001",
                        old.incarnation,old.pid,
                        old.cgroup,old.process_start_ticks)
                else:
                    old=ctl.current
                    ctl.current=ServiceIdentity(
                        old.boot_id,old.incarnation,
                        old.pid+1 if fault=="unresponsive_worker" else old.pid,
                        old.cgroup,old.process_start_ticks+
                            (1 if fault=="process_birth_drift" else 0))
                assert (await client.get(base+"/uses/"+useid)).status_code==409
                await assert_fenced(client,ctl)
                waiting=await client.post("/resource/leases",
                    json={"workload":"media-image","source":"next-client"})
                assert waiting.status_code==201
                assert waiting.json()["state"]=="queued"
                assert (await client.delete(base)).status_code==200
                if not ctl.active:
                    ended=await client.delete(base+"/uses/"+useid)
                    assert ended.status_code==503
                state=await assert_fenced(client,ctl)
                assert state["queued_count"]==1
                assert state["resource_leases"]["lease_count"]==2
        # A restart cannot silently clear the persistent recovery fence.
        nextctl=Controller()
        nextsvc=MockServices(nextctl)
        restarted=app(tmp_path,nextctl,nextsvc)
        async with restarted.router.lifespan_context(restarted):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=restarted),
                base_url="http://new-rm-dev") as client:
                health=(await client.get("/health")).json()
                state=(await client.get("/status")).json()
                assert health["status"]=="degraded"
                assert state["admission_blocked"] is True
                assert state["gpu_residency"]["recovery_required"] is True
                assert nextctl.events==[]
    execute(task())


def test_expired_service_start_retains_original_rm_slot(tmp_path):
    class NeverStarts(Controller):
        async def start(self):
            self.events.append("start_wait")
            assert self.residency.marker.exists()
            await asyncio.Event().wait()

    async def task():
        ctl=NeverStarts()
        svc=MockServices(ctl)
        server=app(tmp_path,ctl,svc)
        async with server.router.lifespan_context(server):
            ctl.residency=server.state.resource_leases.residency
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=server),
                base_url="http://rm-dev") as client:
                lease=(await client.post("/resource/leases",
                    json={"workload":"media-image"})).json()
                base=f"/resource/leases/{lease['lease_id']}"
                with pytest.raises(TimeoutError):
                    await asyncio.wait_for(client.post(base+"/uses",
                        json={"provider":"comfyui-local",
                              "capability":"image-generation"}),timeout=.04)
                assert ctl.events==["start_wait"]
                assert (await client.delete(base)).status_code==200
                s=await assert_fenced(client,ctl)
                assert s["resource_leases"]["lease_count"]==1
    execute(task())


def test_expired_service_stop_retains_original_rm_slot(tmp_path):
    class NeverStops(Controller):
        async def stop_and_verify(self, identity):
            self.events.append("stop_wait")
            assert self.running(identity)
            assert self.residency.marker.exists()
            assert self.residency.state=="freeing_comfy"
            await asyncio.Event().wait()

    async def task():
        ctl=NeverStops()
        svc=MockServices(ctl)
        server=app(tmp_path,ctl,svc)
        async with server.router.lifespan_context(server):
            ctl.residency=server.state.resource_leases.residency
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=server),
                base_url="http://rm-dev") as client:
                base,useid=await create_lease(client)
                assert (await client.delete(base)).status_code==200
                with pytest.raises(TimeoutError):
                    await asyncio.wait_for(
                        client.delete(base+"/uses/"+useid),timeout=.04)
                assert ctl.events==["start","stop_wait"]
                s=await assert_fenced(client,ctl)
                assert s["resource_leases"]["lease_count"]==1
                assert ctl.active
    execute(task())


def test_internal_rm_watch_detects_unannounced_process_failure(tmp_path):
    async def task():
        ctl,svc,server=instance(tmp_path)
        async with server.router.lifespan_context(server):
            ctl.residency=server.state.resource_leases.residency
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=server),
                base_url="http://rm-dev") as client:
                base,useid=await create_lease(client)
                assert (await server.state.resource_leases.audit_on_demand_processes())==0
                assert (await client.get("/health")).json()["status"]=="ok"
                # The original client NEVER calls /uses GET or DELETE after exit.
                ctl.active=False
                watched=await server.state.resource_leases.audit_on_demand_processes()
                assert watched==1
                assert await server.state.resource_leases.audit_on_demand_processes()==0
                state=await assert_fenced(client,ctl)
                assert state["resource_leases"]["lease_count"]==1
                assert (await client.delete(base)).status_code==200
                queued=await client.post("/resource/leases",
                    json={"workload":"media-image"})
                assert queued.status_code==201
                assert queued.json()["state"]=="queued"
    execute(task())


def test_background_existing_rm_reaper_reacts_without_client_poll(tmp_path):
    async def task():
        ctl,svc,server=instance(tmp_path)
        async with server.router.lifespan_context(server):
            ctl.residency=server.state.resource_leases.residency
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=server),
                base_url="http://rm-dev") as client:
                base,useid=await create_lease(client)
                ctl.active=False
                # The DEV reaper inside the same Gateway checks at <=2s.
                await asyncio.sleep(2.35)
                state=await assert_fenced(client,ctl)
                assert state["resource_leases"]["lease_count"]==1
                assert ctl.residency.marker.exists()
                assert (await client.delete(base)).status_code==200
    execute(task())
