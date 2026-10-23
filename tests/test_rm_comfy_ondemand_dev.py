"""CPU-only integration of leased ComfyUI start/free/stop with existing RM."""
import asyncio
from pathlib import Path

import httpx
import pytest

from ai_bridge.gateway.app import create_gateway_app
from ai_bridge.gateway.comfy_ondemand_dev import ServiceIdentity
from ai_bridge.settings import Settings


class Controller:
    def __init__(self):
        self.events=[]
        self.active=False
        self.fail_start=False
        self.fail_stop=False
        self.current=None
        self.residency=None

    async def start(self):
        self.events.append("start")
        assert self.residency.marker.exists(), "fence must precede process start"
        if self.fail_start:
            raise RuntimeError("dev start rejected")
        assert not self.active
        self.active=True
        self.current=ServiceIdentity(Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
                                     "a"*32,61001,
                                     "/system.slice/ai-rm-comfy-ondemand-dev.service",123456)
        return self.current

    def running(self, identity):
        return self.active and identity==self.current

    async def stop_and_verify(self, identity):
        self.events.append("stop")
        assert self.running(identity), "controller may not stop foreign process"
        assert self.residency.state=="freeing_comfy"
        assert self.residency.marker.exists(), "fence must survive cleanup"
        if self.fail_stop:
            raise RuntimeError("systemd unit failed to stop")
        self.active=False


class MockServices:
    def __init__(self, controller):
        self.controller=controller
        self.events=[]
        self.cleanup_failed=False
        self.reserved=0
        self.queued=False

    def ollama(self, request):
        self.events.append(("ollama",request.url.path))
        if request.url.path=="/api/ps":
            return httpx.Response(200,json={"models":[]})
        if request.url.path=="/api/tags":
            return httpx.Response(200,json={"models":[]})
        return httpx.Response(200,json={"done":True})

    def comfy(self, request):
        self.events.append(("comfy",request.url.path))
        if not self.controller.active:
            raise httpx.ConnectError("Comfy not running",request=request)
        if request.url.path=="/queue":
            return httpx.Response(200,json={"queue_running":[1] if self.queued else [],
                                           "queue_pending":[]})
        if request.url.path=="/ai-platform/residency":
            return httpx.Response(200,json={"schema_version":1,"loaded_models":0,
                                           "queue_running":0,"queue_pending":0,
                                           "cleanup_pending":False})
        if request.url.path=="/system_stats":
            return httpx.Response(200,json={"devices":[{"torch_vram_total":self.reserved}]})
        if request.url.path=="/free":
            if self.cleanup_failed:
                return httpx.Response(500,json={"error":"cleanup failed"})
            self.reserved=0
            return httpx.Response(200,json={})
        return httpx.Response(404)


def app(tmp_path,controller,service,**overrides):
    values={
        "gateway_host":"127.0.0.1",
        "gateway_port":11435,
        "ollama_url":"http://ollama.fake",
        "gateway_comfy_url":"http://127.0.0.1:11657",
        "gateway_gpu_marker":tmp_path/"comfy-ondemand-recovery.blocked",
        "gateway_gpu_transition_timeout":.15,
        "gateway_max_concurrency":1,
        "gateway_comfy_ondemand_dev_mode":True,
        "gateway_vision_radio_enabled":False,
    }
    values.update(overrides)
    return create_gateway_app(Settings(_env_file=None,**values),
              upstream_transport=httpx.MockTransport(service.ollama),
              residency_transport=httpx.MockTransport(service.comfy),
              comfy_process_controller=controller)


def instance(tmp_path,**opts):
    ctl=Controller()
    svc=MockServices(ctl)
    server=app(tmp_path,ctl,svc,**opts)
    return ctl,svc,server


def test_legacy_disabled_no_controller_required(tmp_path):
    controller=Controller()
    service=MockServices(controller)
    a=app(tmp_path,controller,service,gateway_comfy_ondemand_dev_mode=False)
    assert a is not None


@pytest.mark.parametrize("changes",[
    {"gateway_max_concurrency":2},
    {"gateway_host":"0.0.0.0"},
    {"gateway_vision_radio_enabled":True},
    {"gateway_comfy_url":"http://127.0.0.1:8188"},
    {"gateway_comfy_url":"http://192.168.1.55:11657"},
    {"gateway_comfy_url":"http://127.0.0.1:11657/evil"},
])
def test_refuse_nonisolated_or_concurrent_dev_configuration(tmp_path,changes):
    ctl=Controller()
    svc=MockServices(ctl)
    with pytest.raises(RuntimeError,match="isolated localhost DEV"):
        app(tmp_path,ctl,svc,**changes)


def test_cannot_enable_dev_without_trusted_controller(tmp_path):
    with pytest.raises(RuntimeError,match="isolated localhost DEV"):
        create_gateway_app(Settings(_env_file=None,
            gateway_comfy_ondemand_dev_mode=True,
            gateway_comfy_url="http://127.0.0.1:11657"))


def test_on_demand_lease_stays_pinned_through_cleanup_and_stop(tmp_path):
    async def run():
        controller,svc,server=instance(tmp_path)
        async with server.router.lifespan_context(server):
            controller.residency=server.state.resource_leases.residency
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=server),
                base_url="http://gateway") as client:
                health=(await client.get("/health")).json()
                assert health["status"]=="ok"
                assert not controller.active
                lease=(await client.post("/resource/leases",json={
                    "workload":"media-image","source":"telegram-foto"})).json()
                base=f"/resource/leases/{lease['lease_id']}"
                response=await client.post(base+"/uses",json={
                    "provider":"comfyui-local","capability":"image-generation"})
                assert response.status_code==201,response.text
                use=response.json()["use_id"]
                assert controller.active
                assert controller.events==["start"]
                assert controller.residency.state=="media"
                assert controller.residency.marker.exists()
                assert (await client.get(base+"/uses/"+use)).status_code==200
                waiting=asyncio.create_task(client.post("/api/embed",json={
                    "model":"bge-m3","input":"CAN"}))
                await asyncio.sleep(.01)
                assert not waiting.done(),"priority scheduler bypassed by media"
                status=(await client.get("/status")).json()
                assert status["active_count"]==1
                assert status["queued_count"]==1
                assert (await client.delete(base)).json()["released"]
                assert not waiting.done()
                end=await client.delete(base+"/uses/"+use)
                assert end.status_code==200,end.text
                assert end.json()["released"] is True
                assert controller.events==["start","stop"]
                assert not controller.active
                assert controller.residency.state=="llm"
                assert not controller.residency.marker.exists()
                assert (await waiting).status_code==200
                last=(await client.get("/status")).json()
                assert last["active_count"]==last["queued_count"]==0
                assert last["resource_leases"]["lease_count"]==0
                assert svc.events.index(("comfy","/free")) < len(svc.events)
    asyncio.run(run())


@pytest.mark.parametrize("failure",["start","stop","cleanup","crash"])
def test_failure_retains_dirty_marker_and_global_slot(tmp_path,failure):
    async def run():
        ctl,svc,server=instance(tmp_path)
        ctl.fail_start=failure=="start"
        async with server.router.lifespan_context(server):
            ctl.residency=server.state.resource_leases.residency
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=server),
                base_url="http://gateway") as client:
                lease=(await client.post("/resource/leases",json={
                    "workload":"media-image"})).json()
                base=f"/resource/leases/{lease['lease_id']}"
                start=await client.post(base+"/uses",json={
                    "provider":"comfyui-local","capability":"image-generation"})
                if failure=="start":
                    assert start.status_code==503,start.text
                else:
                    assert start.status_code==201,start.text
                    use=start.json()["use_id"]
                    if failure=="stop":
                        ctl.fail_stop=True
                    elif failure=="cleanup":
                        svc.cleanup_failed=True
                    else:
                        ctl.active=False
                        verify=await client.get(base+"/uses/"+use)
                        assert verify.status_code==409
                    if failure!="crash":
                        released=await client.delete(base+"/uses/"+use)
                        assert released.status_code==503,released.text
                assert (await client.delete(base)).json()["released"]
                status=(await client.get("/status")).json()
                assert status["admission_blocked"] is True
                assert status["active_count"]==1
                assert status["gpu_residency"]["recovery_required"] is True
                assert ctl.residency.marker.exists()
                assert (await client.get("/health")).json()["status"]=="degraded"
    asyncio.run(run())


def test_recovery_marker_prevents_automatic_restart(tmp_path):
    async def run():
        ctl,svc,server=instance(tmp_path)
        ctl.residency=None
        marker=tmp_path/"comfy-ondemand-recovery.blocked"
        marker.write_text("dirty")
        async with server.router.lifespan_context(server):
            ctl.residency=server.state.resource_leases.residency
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=server),
                base_url="http://gateway") as client:
                status=(await client.get("/status")).json()
                assert status["admission_blocked"] is True
                assert status["gpu_residency"]["recovery_required"] is True
                lease=await client.post("/resource/leases",json={
                    "workload":"media-image"})
                assert lease.status_code==201
                assert lease.json()["state"]=="queued"
                assert not ctl.active
                assert ctl.events==[]
    asyncio.run(run())


def test_token_must_be_unchanged_during_lease(tmp_path):
    async def run():
        ctl,svc,server=instance(tmp_path)
        async with server.router.lifespan_context(server):
            ctl.residency=server.state.resource_leases.residency
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=server),
                base_url="http://gateway") as client:
                lease=(await client.post("/resource/leases",json={
                    "workload":"media-image"})).json()
                base=f"/resource/leases/{lease['lease_id']}"
                started=await client.post(base+"/uses",json={
                    "provider":"comfyui-local","capability":"image-generation"})
                assert started.status_code==201
                ctl.current=ServiceIdentity(Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
                    "b"*32,61002,"/system.slice/another.service",654321)
                checked=await client.get(base+"/uses/"+started.json()["use_id"])
                assert checked.status_code==409
                status=(await client.get("/status")).json()
                assert status["gpu_residency"]["recovery_required"] is True
                assert status["active_count"]==1
    asyncio.run(run())
