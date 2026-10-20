"""CPU-only ASGI coverage: real scheduling/residency, mocked provider HTTP."""
import asyncio

import httpx
import pytest

from ai_bridge.gateway.app import create_gateway_app
from ai_bridge.gateway.engine_lifecycle import (
    ComfyUILifecycle, EngineLifecycleError, OllamaLifecycle, lifecycle_for,
)
from ai_bridge.settings import Settings
from test_gateway_priority_classes import api_client
from test_gpu_residency import Providers


@pytest.fixture
def anyio_backend():
    return "asyncio"


def make_app(tmp_path, handler):
    transport = httpx.MockTransport(handler)
    return create_gateway_app(
        Settings(_env_file=None, ollama_url="http://ollama.test",
                 gateway_gpu_marker=tmp_path / "gpu.dirty",
                 gateway_gpu_transition_timeout=.04),
        upstream_transport=transport, residency_transport=transport,
    )


@pytest.mark.anyio
@pytest.mark.parametrize("leased", [False, True])
@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("state", ["llm", "media", "blocked", "draining_ollama", "freeing_comfy"])
async def test_ollama_contract_before_dispatch(tmp_path, monkeypatch, leased, stream, state):
    calls, hooks = [], []

    def handle(request):
        calls.append(request.url.path)
        async def chunks():
            yield b'{"response":"ok"}\n'
        return httpx.Response(200, content=chunks())

    original = OllamaLifecycle.prepare

    async def prepare(self, residency):
        hooks.append("prepare")
        await original(self, residency)

    monkeypatch.setattr(OllamaLifecycle, "prepare", prepare)
    app = make_app(tmp_path, handle)
    async with api_client(app) as client:
        leases = app.state.resource_leases
        assert leases.scheduler is app.state.scheduler
        headers = {"x-ai-engine": "vision-local", "x-ai-resource-state": "IDLE",
                   "x-ai-gpu-reuse-safe": "true"}
        if leased:
            lease = (await client.post("/resource/leases", json={})).json()
            headers.update({"x-ai-resource-lease": lease["lease_id"],
                            "x-ai-resource-lease-release": "1"})
        leases.residency.state = state
        response = await client.post("/api/chat", json={"stream": stream}, headers=headers)
        assert response.status_code == (200 if state == "llm" else 503)
        assert hooks == ["prepare"]
        assert calls == (["/api/chat"] if state == "llm" else [])
        status = await app.state.scheduler.snapshot()
        if state == "llm":
            assert status["active_count"] == status["queued_count"] == 0
            assert (await leases.snapshot())["lease_count"] == 0
            assert leases.residency.state == state
        else:
            # Failed engine guard MUST hold the original slot/lease and mark
            # the device dirty; this is a safety fence, not a routine 503.
            assert status["admission_blocked"] is True
            assert status["active_count"] == 1
            assert status["queued_count"] == 0
            assert leases.residency.state == "blocked"
            assert leases.residency.marker.exists()
            assert (await leases.snapshot())["lease_count"] == (1 if leased else 0)


@pytest.mark.anyio
async def test_comfy_contract_pins_existing_scheduler_and_verifies(tmp_path, monkeypatch):
    providers, hooks = Providers(), []
    providers.models = []
    for name in ("prepare", "release"):
        original = getattr(ComfyUILifecycle, name)

        async def hook(self, residency, original=original, name=name):
            hooks.append(name)
            assert (await app.state.resource_leases.snapshot())["leases"][0]["external_in_use"]
            await original(self, residency)

        monkeypatch.setattr(ComfyUILifecycle, name, hook)
    original_verify = ComfyUILifecycle.verify_active

    def verify(self, residency):
        hooks.append("verify_active")
        return original_verify(self, residency)

    monkeypatch.setattr(ComfyUILifecycle, "verify_active", verify)
    app = make_app(tmp_path, providers.handle)
    async with api_client(app) as client:
        lease = (await client.post("/resource/leases", json={})).json()
        path = f"/resource/leases/{lease['lease_id']}"
        response = await client.post(path + "/uses", json={
            "provider": "comfyui-local", "capability": "image-generation"})
        assert response.status_code == 201
        use = path + "/uses/" + response.json()["use_id"]
        assert (await client.get(use)).status_code == 200
        # The actual Gateway snapshot contains tuple-shaped job.workload.
        rm = (await client.get("/status")).json()["resource_manager"]
        assert rm["state"] == "RUNNING" and rm["active_engine"] == "comfyui"
        assert app.state.resource_leases.residency.marker.exists()
        assert (await client.delete(path)).json()["released"]
        assert (await app.state.scheduler.snapshot())["active_count"] == 1
        assert (await client.delete(use)).json()["released"]
        assert hooks == ["prepare", "verify_active", "release"]
        assert providers.calls.count("/free") == 1
        assert (await app.state.scheduler.snapshot())["active_count"] == 0
        evidence = app.state.resource_leases.residency.evidence_snapshot()
        assert evidence["GPU_REUSE_SAFE"]["status"] == "NOT_VERIFIED"


@pytest.mark.anyio
@pytest.mark.parametrize("phase", ["prepare", "release"])
@pytest.mark.parametrize("failure", ["http", "timeout", "cancel"])
async def test_external_failure_retains_owner_and_marker(tmp_path, phase, failure):
    providers = Providers()
    providers.models = []
    failing = False
    entered = asyncio.Event()

    async def handle(request):
        if failing:
            entered.set()
            if failure == "http":
                return httpx.Response(500)
            await asyncio.Event().wait()
        return providers.handle(request)

    app = make_app(tmp_path, handle)
    async with api_client(app) as client:
        lease = (await client.post("/resource/leases", json={})).json()
        path = f"/resource/leases/{lease['lease_id']}"
        payload = {"provider": "comfyui-local", "capability": "image-generation"}
        if phase == "release":
            use_id = (await client.post(path + "/uses", json=payload)).json()["use_id"]
        failing = True
        request = (client.post(path + "/uses", json=payload) if phase == "prepare"
                   else client.delete(path + "/uses/" + use_id))
        task = asyncio.create_task(request)
        if failure == "cancel":
            await entered.wait()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            assert (await task).status_code == 503
        leases = app.state.resource_leases
        assert leases.residency.state == "blocked"
        assert leases.residency.marker.exists()
        assert app.state.scheduler.admission_blocked
        assert (await client.delete(path)).json()["released"]
        assert await leases.reap_expired() == 0
        snapshot = await leases.snapshot()
        assert snapshot["leases"][0]["external_in_use"]
        assert snapshot["leases"][0]["in_use"] == 0
        assert (await app.state.scheduler.snapshot())["active_count"] == 1


@pytest.mark.anyio
@pytest.mark.parametrize("provider", ["vision-local", "unknown-local", "ollama-local"])
async def test_http_cannot_register_or_authorize_external_adapter(tmp_path, provider):
    def forbidden(request):
        pytest.fail("denied provider must not dispatch")

    app = make_app(tmp_path, forbidden)
    async with api_client(app) as client:
        lease = (await client.post("/resource/leases", json={})).json()
        response = await client.post(f"/resource/leases/{lease['lease_id']}/uses", json={
            "provider": provider, "capability": "image-generation"},
            headers={"x-ai-engine-available": "true", "x-ai-gpu-grant": "true"})
        assert response.status_code == 400
        assert not (await app.state.resource_leases.snapshot())["leases"][0]["external_in_use"]
        await client.delete(f"/resource/leases/{lease['lease_id']}")


def test_fixed_stateless_contract_does_not_grant_new_engines():
    for provider in ("ollama-local", "comfyui-local"):
        adapter = lifecycle_for(provider)
        assert not hasattr(adapter, "__dict__")
        assert lifecycle_for(provider) is adapter
    with pytest.raises(EngineLifecycleError, match="DENIED_UNAVAILABLE"):
        lifecycle_for("vision-local")
    with pytest.raises(EngineLifecycleError):
        lifecycle_for("future-local")
    # An independently implemented protocol is not automatically admitted.
    class FutureLifecycle(OllamaLifecycle):
        __slots__ = ()
    assert not hasattr(FutureLifecycle(), "__dict__")
    with pytest.raises(EngineLifecycleError):
        lifecycle_for("future-local", external=True)
