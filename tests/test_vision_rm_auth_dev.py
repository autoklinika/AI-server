"""Credential gate regression: real HTTP routes but no production network or GPU."""
import httpx
import pytest
from pathlib import Path
from ai_bridge.gateway.app import create_gateway_app
from ai_bridge.settings import Settings
from test_gateway_priority_classes import api_client
from test_gpu_residency import Providers

TOKEN="test-only-vision-executor-secret-with-40-bytes"
@pytest.fixture
def anyio_backend():return "asyncio"

def test_opt_in_without_credential_denied_at_startup(tmp_path):
    with pytest.raises(ValueError,match="executor credential"):
        create_gateway_app(Settings(_env_file=None,gateway_vision_external_enabled=True,
                                     gateway_gpu_marker=tmp_path/"dev"))
    with pytest.raises(ValueError):
        create_gateway_app(Settings(_env_file=None,gateway_vision_external_enabled=True,
                                   gateway_vision_executor_token="short",
                                   gateway_vision_worker_gate_sha256="a"*64,
            gateway_vision_allowed_scripts={"/dummy/script.py":"a"*64},
            gateway_vision_strict_gpu_clients=False,
                                   gateway_gpu_marker=tmp_path/"dev"))

@pytest.mark.anyio
async def test_unauthenticated_client_denied_every_lease_route(tmp_path):
    providers=Providers(); providers.models=[]
    app=create_gateway_app(Settings(_env_file=None,gateway_vision_external_enabled=True,
            gateway_vision_executor_token=TOKEN,
            gateway_vision_worker_gate_sha256="a"*64,
            gateway_vision_allowed_scripts={"/dummy/script.py":"a"*64},
            gateway_vision_strict_gpu_clients=False,gateway_gpu_marker=tmp_path/"marker"),
            upstream_transport=httpx.MockTransport(providers.handle),
            residency_transport=httpx.MockTransport(providers.handle))
    async with api_client(app) as client:
        denied=await client.post("/resource/leases",json={"workload":"vision-benchmark"})
        assert denied.status_code==403 and denied.json()=={"detail":"executor_not_authorized"}
        assert (await client.post("/resource/leases",json={"workload":"external"})).status_code==403
        assert (await client.get("/resource/leases/guess")).status_code==403
        assert (await client.delete("/resource/leases/guess")).status_code==403
        assert (await client.post("/resource/leases/guess/heartbeat")).status_code==403
        assert (await client.get("/resource/leases/guess/uses/guess")).status_code==403
        assert (await client.post("/resource/leases/guess/uses",json={})).status_code==403
        assert (await client.delete("/resource/leases/guess/uses/guess")).status_code==403
        assert (await client.post("/resource/leases",json={"workload":"vision-benchmark"},
                                  headers={"x-ai-vision-executor-token":"bad"})).status_code==403
        state=(await client.get("/status")).json()
        assert not state["active"] and state["resource_leases"]["lease_count"]==0
        client.headers["x-ai-vision-executor-token"]=TOKEN
        created=await client.post("/resource/leases",json={"workload":"vision-benchmark"})
        assert created.status_code==201
        lease=created.json()["lease_id"]
        assert (await client.get("/resource/leases/"+lease)).status_code==200
        assert (await client.post("/resource/leases/"+lease+"/heartbeat")).status_code==200
        assert (await client.delete("/resource/leases/"+lease)).status_code==200
        assert (await client.get("/status")).json()["resource_leases"]["lease_count"]==0

@pytest.mark.anyio
async def test_flag_off_keeps_legacy_lease_contract(tmp_path):
    app=create_gateway_app(Settings(_env_file=None,gateway_gpu_marker=tmp_path/"marker"),
            upstream_transport=httpx.MockTransport(Providers().handle),
            residency_transport=httpx.MockTransport(Providers().handle))
    async with api_client(app) as client:
        r=await client.post("/resource/leases",json={"workload":"external"})
        assert r.status_code==201
        assert (await client.delete("/resource/leases/"+r.json()["lease_id"])).status_code==200


def test_strict_cross_uid_requires_explicit_model_uid(tmp_path):
    # Even with a socket path, do not infer ai-vision UID from Gateway's UID.
    import pytest
    from ai_bridge.gateway.app import create_gateway_app
    from ai_bridge.settings import Settings
    settings=Settings(_env_file=None,gateway_vision_external_enabled=True,
        gateway_vision_executor_token=TOKEN,
        gateway_vision_allowed_scripts={"/dummy/script.py":"a"*64},
        gateway_vision_worker_gate_sha256="a"*64,
        gateway_gpu_marker=tmp_path/"marker",
        gateway_vision_strict_gpu_clients=True,
        gateway_vision_gpu_observer_socket=tmp_path/"gpu-observer.sock")
    with pytest.raises(ValueError,match="pinned worker UID"):
        create_gateway_app(settings)
    approved=settings.model_copy(update={"gateway_vision_worker_uid":994})
    app=create_gateway_app(approved)
    assert app is not None
