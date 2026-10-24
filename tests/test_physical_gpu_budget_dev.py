"""Memory and request boundaries are fail closed; no CUDA required for CI."""
import asyncio
import json

import httpx
import pytest

from ai_bridge.gateway.app import create_gateway_app
from ai_bridge.gateway.physical_gpu_budget import (
    MemoryObservation, PhysicalGPUBudget, PhysicalGPUBudgetDenied,
    validate_bounded_model_request,
)
from ai_bridge.settings import Settings

ROUTES = {"qwen3:0.6b":"amd","bge-m3:latest":"rtx"}
ENDPOINTS = {"amd":"http://127.0.0.1:11641","rtx":"http://127.0.0.1:11642"}
CONF = {"host_reserve_mib":8192,"rtx_reserve_mib":3072,
        "pools":{
            "amd":{"max_pool_mib":4096,"models_mib":{"qwen3:0.6b":1536}},
            "rtx":{"max_pool_mib":8192,"models_mib":{"bge-m3:latest":2048}},
        }}
GOOD = MemoryObservation(30720,24576,16311,2,15941)

def policy(c=None):
    return PhysicalGPUBudget.from_json(json.dumps(c or CONF),ROUTES)

def test_valid_budget_uses_only_real_ram_and_rtx_vram():
    p=policy()
    assert p.evaluate(gpu="amd",model="qwen3:0.6b",loaded=set(),metrics=GOOD)["incremental_mib"]==1536
    assert p.evaluate(gpu="rtx",model="bge-m3:latest",loaded=set(),metrics=GOOD)["incremental_mib"]==2048
    assert p.snapshot()["vulkan_memory_budget"]=="IGNORED_AS_UNTRUSTWORTHY"
    assert p.snapshot()["hard_kernel_gpu_vram_enforcement"]=="NOT_AVAILABLE"

@pytest.mark.parametrize("metrics,target,reason",[
    (MemoryObservation(30720,8500,16311,2,15941),"amd","MemAvailable"),
    (MemoryObservation(2048,2048,16311,2,15941),"amd","reserve"),
    (MemoryObservation(30720,24576,16311,14900,1000),"rtx","occupancy"),
    (MemoryObservation(30720,24576,16311,1000,2000),"rtx","reserve"),
    (MemoryObservation(30720,40000,16311,2,15941),"amd","inconsistent"),
    (MemoryObservation(30720,24576,16311,2,20000),"rtx","inconsistent"),
    (MemoryObservation(30720,24576,16311,-1,15941),"rtx","incomplete"),
])
def test_low_ram_vram_and_bad_metrics_fail_closed(metrics,target,reason):
    model="qwen3:0.6b" if target=="amd" else "bge-m3:latest"
    with pytest.raises(PhysicalGPUBudgetDenied):
        policy().evaluate(gpu=target,model=model,loaded=set(),metrics=metrics)

def test_resident_model_not_counted_twice_but_unknown_residency_fails():
    m=policy()
    value=m.evaluate(gpu="rtx",model="bge-m3:latest",
                     loaded={"bge-m3:latest"},metrics=MemoryObservation(30720,24576,16311,1800,14000))
    assert value["incremental_mib"]==0
    with pytest.raises(PhysicalGPUBudgetDenied,match="unrecognized"):
        m.evaluate(gpu="rtx",model="bge-m3:latest",loaded={"unknown"},metrics=GOOD)

def test_routing_without_complete_budget_fails_closed():
    with pytest.raises(PhysicalGPUBudgetDenied):
        PhysicalGPUBudget.from_json("",ROUTES)
    with pytest.raises(PhysicalGPUBudgetDenied):
        PhysicalGPUBudget.from_json("{}",ROUTES)
    bad=json.loads(json.dumps(CONF))
    del bad["pools"]["rtx"]["models_mib"]["bge-m3:latest"]
    with pytest.raises(PhysicalGPUBudgetDenied):
        PhysicalGPUBudget.from_json(json.dumps(bad),ROUTES)
    bad=json.loads(json.dumps(CONF))
    bad["pools"]["amd"]["models_mib"]={"bge-m3:latest":1024}
    with pytest.raises(PhysicalGPUBudgetDenied):
        PhysicalGPUBudget.from_json(json.dumps(bad),ROUTES)
    bad=json.loads(json.dumps(CONF))
    bad["rtx_reserve_mib"]=1
    with pytest.raises(PhysicalGPUBudgetDenied):
        PhysicalGPUBudget.from_json(json.dumps(bad),ROUTES)
    bad=json.loads(json.dumps(CONF))
    bad["pools"]["amd"]["models_mib"]["qwen3:0.6b"]=False
    with pytest.raises(PhysicalGPUBudgetDenied):
        PhysicalGPUBudget.from_json(json.dumps(bad),ROUTES)

@pytest.mark.parametrize("payload",[
 {"model":"qwen3:0.6b","options":{"num_ctx":65536}},
 {"model":"qwen3:0.6b","options":{"num_gpu":0}},
 {"model":"qwen3:0.6b","options":{"main_gpu":1}},
 {"model":"qwen3:0.6b","options":{"num_predict":100000}},
 {"model":"qwen3:0.6b","options":{"num_batch":32768}},
 {"model":"qwen3:0.6b","context_length":128000},
 {"model":"qwen3:0.6b","max_tokens":100000},
 {"model":"qwen3:0.6b","keep_alive":-1},
 {"model":"qwen3:0.6b","keep_alive":"1h"},
 {"model":"qwen3:0.6b","keep_alive":True},
 {"model":"qwen3:0.6b","options":{"num_ctx":True}},
 {"model":"qwen3:0.6b","options":[]},
])
def test_unsafe_gpu_memory_request_knobs_denied(payload):
    with pytest.raises(PhysicalGPUBudgetDenied):
        validate_bounded_model_request(json.dumps(payload).encode())

def test_bounded_keepalive_context_request_accepted():
    assert validate_bounded_model_request(json.dumps({
        "model":"qwen3:0.6b","options":{"num_ctx":512,"num_predict":32},
        "keep_alive":"3m"}).encode())=="qwen3:0.6b"

def _settings(tmp_path):
    return Settings(ollama_url="http://ollama.local",
        gateway_comfy_url="http://comfy.local",
        gateway_vision_radio_enabled=False,
        gateway_gpu_marker=tmp_path/"residency-marker",
        gateway_physical_ollama_routes_json=json.dumps({
            "endpoints":ENDPOINTS,"models":ROUTES}),
        gateway_physical_gpu_budget_json=json.dumps(CONF),
        gateway_physical_gpu_dev_mode=True,
        gateway_max_concurrency=1)

@pytest.mark.parametrize("scenario",[
    "low_host_ram", "low_rtx_vram", "unavailable_metrics",
    "unknown_loaded_model", "target_inventory_unavailable",
])
def test_dev_gateway_refuses_unsafe_physical_memory_and_releases_single_slot(
    tmp_path,scenario,
):
    async def run():
        calls=[]
        async def handler(req):
            calls.append((req.method,req.url.path))
            if req.url.path=="/api/ps":
                if scenario=="target_inventory_unavailable":
                    return httpx.Response(500,json={"error":"busy"})
                return httpx.Response(200,json={"models":[{"name":"unknown"}]} if
                    scenario=="unknown_loaded_model" else {"models":[]})
            return httpx.Response(200,json={"ok":True})
        async def no_metrics():
            raise RuntimeError("not used")
        def probe():
            if scenario=="unavailable_metrics":raise RuntimeError("nvidia-smi unavailable")
            if scenario=="low_host_ram":
                return MemoryObservation(30720,8192,16311,2,15941)
            return MemoryObservation(30720,24576,16311,14000,2000) if scenario=="low_rtx_vram" else GOOD
        trans=httpx.MockTransport(handler)
        app=create_gateway_app(_settings(tmp_path),
            upstream_transport=trans,residency_transport=trans,
            gpu_memory_probe=probe)
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://dev-rm") as client:
                r=await client.post("/api/embed",json={
                    "model":"bge-m3:latest","input":"CAN"})
                assert r.status_code==503
                assert r.json()["error"]=="physical_gpu_budget_denied"
                assert not any(path=="/api/embed" for _,path in calls)
                status=(await client.get("/status")).json()
                assert status["active_count"]==status["queued_count"]==0
                assert status["physical_gpu_budget"]["vulkan_memory_budget"]=="IGNORED_AS_UNTRUSTWORTHY"
                assert not (tmp_path/"residency-marker").exists()
    asyncio.run(run())

def test_enabled_router_must_have_memory_budget(tmp_path):
    with pytest.raises(PhysicalGPUBudgetDenied):
        create_gateway_app(Settings(
            gateway_physical_ollama_routes_json=json.dumps({
                "endpoints":ENDPOINTS,"models":ROUTES}),
            gateway_physical_gpu_budget_json="",
            gateway_physical_gpu_dev_mode=True))


def test_reject_oversized_dev_request_body():
    with pytest.raises(PhysicalGPUBudgetDenied):
        validate_bounded_model_request(
            json.dumps({"model":"qwen3:0.6b",
                        "prompt":"A"*300000}).encode())
