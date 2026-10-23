"""DEV-only static physical device routing within ONE existing RM queue."""
import asyncio
import json

import httpx
import pytest

from ai_bridge.gateway.app import create_gateway_app
from ai_bridge.gateway.physical_ollama_routing import (
    PhysicalOllamaRouter, GPUModelRouteRejected,
)
from ai_bridge.settings import Settings

CONFIG = json.dumps({
    "endpoints": {
        "amd": "http://127.0.0.1:11641",
        "rtx": "http://127.0.0.1:11642",
    },
    "models": {
        "qwen3:0.6b": "amd",
        "bge-m3:latest": "rtx",
    },
})

def settings(tmp_path, **overrides):
    args = {
        "ollama_url": "http://ollama.local",
        "gateway_comfy_url": "http://comfy.local",
        "gateway_gpu_marker": tmp_path/"isolated-gpu-state",
        "gateway_max_concurrency": 1,
        "gateway_physical_ollama_routes_json": CONFIG,
        "gateway_vision_radio_enabled": False,
    }
    args.update(overrides)
    return Settings(**args)

def test_default_disabled_and_strict_target_validation():
    assert PhysicalOllamaRouter.from_json("") is None
    assert PhysicalOllamaRouter.from_json(None) is None
    spec=PhysicalOllamaRouter.from_json(CONFIG)
    assert spec.resolve(b'{"model":"qwen3:0.6b"}',"/api/chat")==(
        "http://127.0.0.1:11641/api/chat","amd")
    assert spec.resolve(b'{"model":"bge-m3:latest"}',"/api/embed")==(
        "http://127.0.0.1:11642/api/embed","rtx")
    assert spec.snapshot()["os_enforced_exclusivity"]=="NOT_VERIFIED"
    assert spec.snapshot()["n1_gpu_grants"]=="NOT_ADMITTED"

@pytest.mark.parametrize("url",[
    "http://localhost:11641", "http://192.168.1.55:11641",
    "http://127.0.0.1:11434", "http://127.0.0.1:11435",
    "http://127.0.0.1", "http://user:password@127.0.0.1:11641",
    "https://127.0.0.1:11641","http://127.0.0.1:11641/bypass",
    "http://127.0.0.1:11641?model=evil",
    "http://127.0.0.1:11641#anchor","http://127.0.0.1:99999",
])
def test_refuse_bad_or_nonloopback_target(url):
    config=json.loads(CONFIG)
    config["endpoints"]["amd"]=url
    with pytest.raises(GPUModelRouteRejected):
        PhysicalOllamaRouter.from_json(json.dumps(config))

@pytest.mark.parametrize("payload",[
    b'{}',b'not json',b'[]',b'{"model":"not-routed"}',
    b'{"model":0}',b'{"model":"qwen3:0.6b","endpoint":"http://evil.com"}'
])
def test_refuse_missing_or_unrouted_model(payload):
    r=PhysicalOllamaRouter.from_json(CONFIG)
    if payload.startswith(b'{"model":"qwen3:0.6b"'):
        assert r.resolve(payload,"/api/chat")[1]=="amd"  # ignored caller's endpoint
    else:
        with pytest.raises(GPUModelRouteRejected):
            r.resolve(payload,"/api/chat")

def test_refuse_unsupported_endpoint():
    r=PhysicalOllamaRouter.from_json(CONFIG)
    with pytest.raises(GPUModelRouteRejected):
        r.resolve(b'{"model":"qwen3:0.6b"}',"/api/ps")

def test_refuse_incomplete_mapping():
    c=json.loads(CONFIG)
    c["models"]={"qwen3:0.6b":"amd"}
    with pytest.raises(GPUModelRouteRejected):
        PhysicalOllamaRouter.from_json(json.dumps(c))

def test_refuse_second_concurrent_scheduler_or_radio(tmp_path):
    with pytest.raises(RuntimeError,match="single|one global RM"):
        create_gateway_app(settings(tmp_path,gateway_max_concurrency=2))
    with pytest.raises(RuntimeError,match="single|one global RM"):
        create_gateway_app(settings(tmp_path,gateway_vision_radio_enabled=True))

def test_routes_exact_models_only_inside_gateway_single_scheduler(tmp_path):
    async def go():
        destinations=[]
        async def handler(request):
            destinations.append((request.url.host,request.url.port,request.url.path))
            if request.url.path=="/api/tags":
                return httpx.Response(200,json={"models":[]})
            return httpx.Response(200,json={"ok":True})
        transport=httpx.MockTransport(handler)
        app=create_gateway_app(settings(tmp_path),
             upstream_transport=transport, residency_transport=transport)
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://gateway",
            ) as client:
                a=await client.post("/api/chat",
                    json={"model":"qwen3:0.6b","stream":False})
                b=await client.post("/api/embed",
                    json={"model":"bge-m3:latest","input":"CAN"})
                bad=await client.post("/api/chat",
                    json={"model":"unknown","stream":False})
                lease=await client.post("/api/chat",
                    json={"model":"qwen3:0.6b","stream":False},
                    headers={"X-AI-Resource-Lease":"forbidden"})
                health=(await client.get("/health")).json()
                snapshot=(await client.get("/status")).json()
                assert a.status_code==b.status_code==200
                assert a.headers["x-ai-gpu-route"]=="amd"
                assert b.headers["x-ai-gpu-route"]=="rtx"
                assert bad.status_code==422 and bad.json()["error"]=="model_gpu_route_denied"
                assert lease.status_code==409 and lease.json()["error"]=="gpu_route_lease_not_supported"
                assert destinations[:2]==[
                    ("127.0.0.1",11641,"/api/chat"),
                    ("127.0.0.1",11642,"/api/embed"),
                ]
                assert not any(x[0]=="evil.com" for x in destinations)
                assert health["physical_gpu_routing"]["mode"]=="dev_static_loopback"
                assert health["scheduler"]["max_concurrency"]==1
                assert snapshot["scheduler"]["active_count"]==0 if "scheduler" in snapshot else snapshot["active_count"]==0
                assert snapshot["physical_gpu_routing"]["n1_gpu_grants"]=="NOT_ADMITTED"
    asyncio.run(go())

def test_gateway_has_one_global_queue_across_both_physical_backends(tmp_path):
    async def go():
        first_started=asyncio.Event()
        release=asyncio.Event()
        seen=[]
        async def handler(request):
            if request.url.path=="/api/tags":
                return httpx.Response(200,json={"models":[]})
            seen.append(request.url.port)
            if request.url.port==11641:
                first_started.set()
                await release.wait()
            return httpx.Response(200,json={"ok":True})
        transport=httpx.MockTransport(handler)
        app=create_gateway_app(settings(tmp_path),
            upstream_transport=transport,residency_transport=transport)
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://gateway") as client:
                a=asyncio.create_task(client.post("/api/chat",
                    json={"model":"qwen3:0.6b","stream":False}))
                await asyncio.wait_for(first_started.wait(),3)
                b=asyncio.create_task(client.post("/api/embed",
                    json={"model":"bge-m3:latest","input":"x"}))
                await asyncio.sleep(.03)
                assert seen==[11641] # second cannot bypass the existing RM slot
                snapshot=(await client.get("/status")).json()
                assert snapshot["active_count"]==1
                assert snapshot["queued_count"]==1
                release.set()
                responses=await asyncio.gather(a,b)
                assert all(r.status_code==200 for r in responses)
                assert seen==[11641,11642]
                final=(await client.get("/status")).json()
                assert final["active_count"]==0 and final["queued_count"]==0
    asyncio.run(go())

def test_legacy_path_unchanged_when_feature_off(tmp_path):
    async def go():
        ports=[]
        async def handler(request):
            ports.append(request.url.host)
            return httpx.Response(200,json={"ok":True})
        m=httpx.MockTransport(handler)
        app=create_gateway_app(settings(tmp_path,
            gateway_physical_ollama_routes_json=""),
            upstream_transport=m,residency_transport=m)
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://gateway") as client:
                r=await client.post("/api/chat",
                    json={"model":"some-other-model","stream":False})
                assert r.status_code==200 and "x-ai-gpu-route" not in r.headers
                assert ports==["ollama.local"]
    asyncio.run(go())

def test_streaming_path_uses_selected_physical_backend(tmp_path):
    async def go():
        targets=[]
        class Stream(httpx.AsyncByteStream):
            async def __aiter__(self):
                yield b'{"response":"ok","done":true}\n'
            async def aclose(self):
                pass
        async def upstream(request):
            targets.append((request.url.port,request.url.path))
            return httpx.Response(200,
                headers={"content-type":"application/x-ndjson"},
                stream=Stream())
        backend=httpx.MockTransport(upstream)
        app=create_gateway_app(settings(tmp_path),
            upstream_transport=backend,residency_transport=backend)
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://dev-rm") as client:
                a=await client.post("/api/generate",json={
                    "model":"qwen3:0.6b","stream":True})
                assert a.status_code==200
                assert a.headers["x-ai-gpu-route"]=="amd"
                assert a.content==b'{"response":"ok","done":true}\n'
                assert targets==[(11641,"/api/generate")]
                state=(await client.get("/status")).json()
                assert state["active_count"]==0
    asyncio.run(go())
