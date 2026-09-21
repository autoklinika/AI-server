"""D.5 offline client regressions; no product processes or network services."""
import argparse
import asyncio
from contextlib import asynccontextmanager
from concurrent.futures import Future
import importlib.util
import json
from pathlib import Path
import sys
import threading
from types import SimpleNamespace

import httpx
import pytest

from ai_bridge.gateway.app import create_gateway_app
from ai_bridge.settings import Settings

ROOT = Path(__file__).resolve().parents[1]


def load_tool(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


resource = load_tool("d5_resource", "tools/hermes_resource_queue.py")


@asynccontextmanager
async def gateway(handler):
    app = create_gateway_app(
        Settings(ollama_url="http://backend", gateway_max_concurrency=1),
        upstream_transport=httpx.MockTransport(handler),
    )
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://gateway"
        ) as client:
            yield app, client


@pytest.mark.parametrize("legacy,canonical,priority,domain,capability", [
    ("/clients/ventilation/api/chat", "/api/chat", 10, "wvc", "reasoning"),
    ("/clients/hermes/v1/chat/completions", "/v1/chat/completions", 50, "shared", "chat"),
    ("/clients/hermes/v1/embeddings", "/v1/embeddings", 50, "shared", "embeddings"),
])
@pytest.mark.parametrize("status", [200, 400, 500])
@pytest.mark.parametrize("stream", [False, True])
def test_legacy_endpoints_preserve_wire_contract_and_v2_jobs(
    legacy, canonical, priority, domain, capability, status, stream, caplog
):
    async def run():
        seen = []
        payload = {"model": "unchanged", "stream": stream,
                   "messages": [{"role": "user", "content": "PRIVATE-D5-PROMPT"}],
                   "tools": [{"type": "function", "function": {"name": "lookup"}}]}
        raw = json.dumps(payload, indent=2).encode()
        wire = b'data: {"choices":[{"delta":{"content":"reply"}}]}\n\ndata: [DONE]\n\n' if stream else b'{"reply":"unchanged"}'

        def handler(request):
            seen.append(request)
            return httpx.Response(status, headers={"content-type": "text/event-stream" if stream else "application/json", "x-request-id": "upstream-id"}, stream=httpx.ByteStream(wire))

        async with gateway(handler) as (app, client):
            for path in (legacy, canonical):
                response = await client.post(path, content=raw, headers={"content-type": "application/json"})
                assert response.status_code == status
                assert response.content == wire
                assert response.headers["x-request-id"] == "upstream-id"
                assert response.headers["x-ai-job-id"].startswith("job_")
                assert response.headers["x-ai-request-id"].startswith("req_")
                if path == legacy:
                    assert response.headers["x-ai-gateway-priority"] == str(priority)
            assert all(request.url.path == canonical and request.content == raw for request in seen)
            snapshot = (await client.get("/status")).json()
            job = snapshot["recent_jobs"][0]
            assert (job["domain"], job["capability"]) == (domain, capability)
            assert job["assigned_provider"] == "ollama-local"
            assert job["state"] == ("completed" if status == 200 else "failed")
            assert snapshot["active_count"] == snapshot["queued_count"] == 0
            assert "PRIVATE-D5-PROMPT" not in json.dumps(snapshot) + caplog.text
    asyncio.run(run())


@pytest.mark.parametrize("path,upstream", [
    ("/api/tags", "/api/tags"), ("/clients/ventilation/api/tags", "/api/tags"),
    ("/v1/models", "/v1/models"), ("/clients/hermes/v1/models", "/v1/models"),
])
def test_inventory_aliases_remain_usable_while_busy(path, upstream):
    async def run():
        seen = []
        def handler(request):
            seen.append(request.url.path)
            return httpx.Response(200, json={"models": []})
        async with gateway(handler) as (app, client):
            lease = (await client.post("/resource/leases", json={})).json()
            result = await asyncio.wait_for(client.get(path), 1)
            assert result.json() == {"models": []}
            assert seen == [upstream]
            await client.delete("/resource/leases/" + lease["lease_id"])
    asyncio.run(run())


@pytest.mark.parametrize("use_gateway,base,expected", [
    (True, "http://gateway", "http://gateway/clients/ventilation"),
    (True, "http://gateway/clients/ventilation/", "http://gateway/clients/ventilation"),
    (False, "http://gateway", "http://recovery"),
])
def test_wvc_entrypoint_keeps_recovery_explicit(monkeypatch, use_gateway, base, expected):
    from ai_bridge.analysis import main as module
    settings = Settings(gateway_url=base, ollama_url="http://recovery", analysis_use_gateway=use_gateway,
                        gateway_priority_ventilation=17)
    monkeypatch.setattr(module, "get_settings", lambda: settings)
    monkeypatch.setattr(module, "build_parser", lambda: SimpleNamespace(parse_args=lambda: argparse.Namespace(
        log_level="INFO", end_at=None, window_minutes=15, source_id="wvc")))
    disposed = []
    monkeypatch.setattr(module, "Database", lambda url: SimpleNamespace(dispose=lambda: disposed.append(True)))
    monkeypatch.setattr(module, "VentilationAnalysisRepository", lambda db: object())
    captured = []
    def adapter(**kwargs):
        captured.append(kwargs)
        return object()
    monkeypatch.setattr(module.OllamaAdapter, "from_endpoint", adapter)
    class StopAfterConstruction(Exception):
        pass
    def service(**kwargs):
        raise StopAfterConstruction()
    monkeypatch.setattr(module, "VentilationAnalysisServiceV122", service)
    with pytest.raises(StopAfterConstruction):
        module.main()
    assert disposed == [True]
    assert len(captured) == 1  # no direct-backend fallback
    assert captured[0]["base_url"] == expected
    assert captured[0]["request_priority"] == (17 if use_gateway else None)
    assert captured[0]["request_source"] == ("ventilation" if use_gateway else None)
    assert captured[0]["default_model"] == settings.ollama_model


async def run_sync(function, **kwargs):
    # Test-only bridge: poll thread completion without relying on a sandboxed
    # event loop's cross-thread self-pipe or its default executor shutdown.
    result = Future()
    def worker():
        try:
            result.set_result(function(**kwargs))
        except BaseException as exc:
            result.set_exception(exc)
    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    async def wait():
        while not result.done():
            await asyncio.sleep(0.001)
        return result.result()
    try:
        return await asyncio.wait_for(wait(), 10)
    finally:
        thread.join(timeout=0.1)


def bridge_helper(monkeypatch, client):
    """Run the unchanged synchronous client against the real ASGI API in-process."""
    loop = asyncio.get_running_loop()
    async def request(method, path, payload):
        response = await client.request(method, path, json=payload)
        if response.is_error:
            raise resource.ResourceQueueError("admission rejected")
        return response.json()
    def sync_json(method, path, payload=None, timeout=5):
        return asyncio.run_coroutine_threadsafe(request(method, path, payload), loop).result(timeout)
    monkeypatch.setattr(resource, "_json", sync_json)
    monkeypatch.setattr(resource.ResourceLease, "start_heartbeat", lambda self: None)
    monkeypatch.setattr(resource, "_float_env", lambda name, default, low, high: 0 if "NOTICE" in name else 0.001)


async def wait_for_queue(app, count):
    async def wait():
        while (await app.state.scheduler.snapshot())["queued_count"] != count:
            await asyncio.sleep(0.001)
    await asyncio.wait_for(wait(), 3)


def test_telegram_multiuser_discord_voice_and_wvc_share_v2_queue(monkeypatch):
    async def run():
        notices, voice, upstream_calls = [], [], []
        def handler(request):
            upstream_calls.append(json.loads(request.content)["messages"][0]["content"])
            return httpx.Response(200, json={"choices": []})
        async with gateway(handler) as (app, client):
            bridge_helper(monkeypatch, client)
            monkeypatch.setattr(resource, "_notify", lambda target, message: notices.append((target, message)))
            first = await run_sync(resource.acquire_resource, target="telegram:101", source="telegram-chat", queue_message="WAIT", start_message="START")
            assert notices == []
            tasks = []
            for index, (target, source) in enumerate((("telegram:202:7", "telegram-chat"), ("discord:303:9", "discord-chat")), 1):
                tasks.append(asyncio.create_task(run_sync(
                    resource.acquire_resource, target=target, source=source,
                    queue_message="WAIT", start_message="START",
                    status_callback=voice.append if source == "discord-chat" else None)))
                await wait_for_queue(app, index)
            wvc = asyncio.create_task(client.post("/clients/ventilation/api/chat", json={"messages": [{"content": "WVC"}]}))
            await wait_for_queue(app, 3)
            # Old caller receives legacy top-level fields and additive v2 metadata.
            status = (await client.get("/resource/leases/" + first.lease_id)).json()
            assert status["state"] == "active" and isinstance(status["job_id"], int)
            assert status["job"]["priority_class"] == "interactive"
            assert {binding["provider"] for binding in status["job"]["workload"]} == {"ollama-local"}
            denied = await client.post(f"/resource/leases/{first.lease_id}/uses", json={"provider": "comfyui-local", "capability": "video-generation"})
            assert denied.status_code == 409
            response = await client.post("/clients/hermes/v1/chat/completions", json={"messages": [{"content": "USER-101"}]}, headers={"X-AI-Resource-Lease": first.lease_id, "X-AI-Resource-Lease-Release": "1"})
            assert response.status_code == 200
            assert (await asyncio.wait_for(wvc, 3)).status_code == 200
            handles = [first]
            for task, content in zip(tasks, ("USER-202", "USER-303")):
                handle = await asyncio.wait_for(task, 3)
                handles.append(handle)
                result = await client.post("/clients/hermes/v1/chat/completions", json={"messages": [{"content": content}]}, headers={"X-AI-Resource-Lease": handle.lease_id, "X-AI-Resource-Lease-Release": "1"})
                assert result.status_code == 200
                assert int(result.headers["x-ai-gateway-job-id"]) == handle.job_id
            for handle in handles:
                await run_sync(handle.release)
            assert len({handle.lease_id for handle in handles}) == 3
            assert upstream_calls == ["USER-101", "WVC", "USER-202", "USER-303"]
            for target in ("telegram:202:7", "discord:303:9"):
                assert [message for recipient, message in notices if recipient == target] == ["WAIT", "START"]
            assert voice == ["queued", "active"]
            snapshot = (await client.get("/status")).json()
            assert snapshot["active_count"] == snapshot["queued_count"] == 0
            assert all(content not in json.dumps(snapshot) for content in upstream_calls)
    asyncio.run(run())


@pytest.mark.parametrize("source,explicit,providers", [
    ("telegram-chat", None, {"ollama-local"}),
    ("discord-chat", None, {"ollama-local"}),
    ("legacy-worker", None, {"ollama-local", "comfyui-local"}),
    ("telegram-chat", "media-video", {"ollama-local", "comfyui-local"}),
])
def test_helper_adapts_known_callers_but_preserves_explicit_and_legacy_plans(monkeypatch, source, explicit, providers):
    async def run():
        async with gateway(lambda request: httpx.Response(200)) as (app, client):
            bridge_helper(monkeypatch, client)
            handle = await run_sync(resource.acquire_resource, target=None, source=source, workload=explicit, priority=73)
            result = (await client.get("/resource/leases/" + handle.lease_id)).json()
            assert result["priority"] == 73
            assert {binding["provider"] for binding in result["job"]["workload"]} == providers
            await run_sync(handle.release)
    asyncio.run(run())


@pytest.mark.parametrize("tool,env", [
    ("tools/local_image/hermes_foto_prompt_compiler.py", "HERMES_FOTO_QWEN_URL"),
    ("tools/local_video/qwen_prompt_compiler.py", "HERMES_VIDEO_QWEN_URL"),
])
@pytest.mark.parametrize("url,allowed", [
    ("http://127.0.0.1:11434/v1/chat/completions", False),
    ("http://localhost/v1/chat/completions", False),
    ("https://example.com:11435/v1/chat/completions", False),
    ("http://127.0.0.1:11435/clients/hermes/v1/chat/completions", True),
    ("http://localhost:11435/v1/chat/completions", True),
    ("http://[::1]:11435/v1/chat/completions", True),
])
def test_media_compilers_cannot_bypass_manager(monkeypatch, tool, env, url, allowed):
    module = load_tool("d5_compiler", tool)
    monkeypatch.setenv(env, url)
    if allowed:
        assert module._gateway_url() == url
    else:
        with pytest.raises(RuntimeError, match="AI Gateway"):
            module._gateway_url()


@pytest.mark.parametrize("kind", ["foto", "video", "video-i2v"])
def test_prompt_compiler_rejects_direct_inference_before_network(monkeypatch, kind):
    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **kw: pytest.fail("direct inference must not execute"))
    if kind == "foto":
        compiler = load_tool("d5_foto_direct", "tools/local_image/hermes_foto_prompt_compiler.py")
        monkeypatch.setenv("HERMES_FOTO_QWEN_URL", "http://127.0.0.1:11434/v1/chat/completions")
        result = compiler.compile_prompt("original request", False)
        assert result["qwen_used"] is False
        assert result["prompt"] == "original request"
        assert "AI Gateway" in result["failure_reason"]
    else:
        monkeypatch.syspath_prepend(str(ROOT / "tools/local_video"))
        compiler = load_tool("d5_video_direct", "tools/local_video/qwen_prompt_compiler_stage30.py")
        monkeypatch.setenv("HERMES_VIDEO_QWEN_URL", "http://127.0.0.1:11434/v1/chat/completions")
        prompt, used, reason, _ = compiler.compile_prompt("original request", has_input_image=kind == "video-i2v")
        assert not used and prompt == "original request" and "AI Gateway" in reason


@pytest.mark.parametrize("kind", ["foto", "video"])
@pytest.mark.parametrize("target", ["telegram:101:7", "discord:202:9"])
@pytest.mark.parametrize("fails", [False, True])
def test_media_wrapper_preserves_target_lease_headers_and_cleanup(monkeypatch, tmp_path, kind, target, fails):
    import io
    import os
    import urllib.request
    monkeypatch.syspath_prepend(str(ROOT / "tools/local_video"))
    monkeypatch.syspath_prepend(str(ROOT / "tools"))
    wrapper_path = "tools/local_image/hermes_foto_dispatch_global.py" if kind == "foto" else "tools/local_video/hermes_video_dispatch_global.py"
    wrapper = load_tool("d5_media_wrapper", wrapper_path)
    compiler = load_tool("d5_media_compiler", "tools/local_image/hermes_foto_prompt_compiler.py" if kind == "foto" else "tools/local_video/qwen_prompt_compiler_stage30.py")
    request_file = tmp_path / "request.json"
    request_file.write_text(json.dumps({"target": target, "prompt": "PRIVATE-MEDIA"}))
    captured, released, requests = [], [], []
    def acquire(**kwargs):
        captured.append(kwargs)
        return SimpleNamespace(lease_id="lease-media", release=lambda: released.append(True))
    monkeypatch.setattr(wrapper.resource, "acquire_resource", acquire)
    monkeypatch.setenv("HERMES_RESOURCE_LEASE_ID", "previous-context")
    monkeypatch.delenv("HERMES_FOTO_QWEN_URL", raising=False)
    monkeypatch.delenv("HERMES_VIDEO_QWEN_URL", raising=False)
    original_request = urllib.request.Request
    def urlopen(request, timeout):
        requests.append(request)
        content = json.dumps({"intent": "generate", "prompt": "compiled"}) if kind == "foto" else "compiled"
        return io.BytesIO(json.dumps({"choices": [{"message": {"content": content}}]}).encode())
    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    def worker(path):
        assert os.environ["HERMES_RESOURCE_LEASE_ID"] == "lease-media"
        if kind == "foto":
            assert compiler._request("PRIVATE-MEDIA", False, 5) == ("generate", "compiled")
        else:
            assert compiler._request_i2v("PRIVATE-MEDIA", 5, duration_seconds=2, motion_level="normal") == "compiled"
        if fails:
            raise RuntimeError("worker failed")
        return 7
    monkeypatch.setattr(wrapper.base if kind == "foto" else wrapper.stage30, "worker" if kind == "foto" else "run_worker", worker)
    execute = lambda: wrapper.worker(tmp_path) if kind == "foto" else wrapper.run_worker(request_file)
    if fails:
        with pytest.raises(RuntimeError, match="worker failed"):
            execute()
    else:
        assert execute() == 7
    assert released == [True]
    assert os.environ["HERMES_RESOURCE_LEASE_ID"] == "previous-context"
    assert urllib.request.Request is original_request
    assert captured[0]["target"] == target
    assert captured[0]["workload"] == ("media-image" if kind == "foto" else "media-video")
    assert captured[0]["queue_message"].startswith("⏳")
    assert captured[0]["start_message"].startswith("▶️")
    assert "PRIVATE-MEDIA" not in json.dumps(captured)
    assert len(requests) == 1
    assert requests[0].get_header("X-ai-resource-lease") == "lease-media"
    assert requests[0].get_header("X-ai-resource-lease-release") is None
    assert b"PRIVATE-MEDIA" in requests[0].data
