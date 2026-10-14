"""B only: CPU/offline observations, never driver or GPU acceptance."""
import asyncio
import json
from contextlib import asynccontextmanager
from datetime import datetime

import httpx
import pytest

from ai_bridge.gateway.app import create_gateway_app
from ai_bridge.gateway.jobs import JobLifecycle
from ai_bridge.gateway.residency import GPUResidency
from ai_bridge.gateway.scheduler import PriorityScheduler
from ai_bridge.settings import Settings
from test_gateway_priority_classes import api_client
from test_gpu_residency import Providers


@pytest.fixture
def anyio_backend():
    return "asyncio"


@asynccontextmanager
async def residency(tmp_path, handler, **kwargs):
    async with httpx.AsyncClient(base_url="http://runtime.test",
                                transport=httpx.MockTransport(handler)) as client:
        yield GPUResidency(
            client, client, tmp_path / "b-marker", timeout=.03, poll=.001,
            **kwargs,
        )


def assert_unproven(gpu):
    facts = gpu.evidence_snapshot()
    assert facts["JOB_TERMINAL"]["status"] == "NOT_OBSERVED"
    assert facts["JOB_TERMINAL"]["job_id"] is None
    assert facts["GPU_REUSE_SAFE"]["status"] == "NOT_VERIFIED"
    assert facts["GPU_REUSE_SAFE"]["device_id"] is None
    assert facts["GPU_REUSE_SAFE"]["generation"] is None
    return facts["MODEL_UNLOADED"]


@pytest.mark.anyio
@pytest.mark.parametrize("terminal", [JobLifecycle.COMPLETED, JobLifecycle.FAILED,
                                      JobLifecycle.CANCELLED])
async def test_specific_terminal_job_does_not_unload_model(tmp_path, terminal):
    providers = Providers()
    scheduler = PriorityScheduler()
    async with residency(tmp_path, providers.handle) as gpu:
        ticket = await scheduler.acquire(priority=50, source="B-test")
        await scheduler.release_job(ticket.job_id, state=terminal)
        snapshot = await scheduler.snapshot()
        job = next(job for job in snapshot["recent_jobs"]
                   if job["job_id"] == ticket.platform_job_id)
        assert job["state"] == terminal
        assert snapshot["active_count"] == 0
        await gpu._json(gpu.ollama, "/api/ps")
        assert assert_unproven(gpu)["ollama"]["models_unloaded"] is False
        assert providers.models == [{"name": "resident"}]


@pytest.mark.anyio
async def test_runtime_unloaded_with_cleanup_pending_stays_blocked(tmp_path):
    providers = Providers()
    async with residency(tmp_path, providers.handle) as gpu:
        await gpu.enter_media()
        providers.cleanup_pending = True
        with pytest.raises(TimeoutError):
            await gpu.leave_media()
        assert gpu.state == "blocked" and gpu.marker.exists()
        models = assert_unproven(gpu)
        assert models["ollama"]["models_unloaded"] is True
        assert models["comfyui"]["status"] == "OBSERVED"
        assert models["comfyui"]["models_unloaded"] is True
        assert models["comfyui"]["cleanup_pending"] is True


@pytest.mark.anyio
async def test_successful_runtime_cleanup_is_only_a_historical_runtime_fact(tmp_path):
    providers = Providers()
    async with residency(tmp_path, providers.handle) as gpu:
        await gpu.enter_media()
        await gpu.leave_media()
        assert gpu.state == "llm" and providers.memory == 0
        models = assert_unproven(gpu)
        for observation in models.values():
            assert observation["models_unloaded"] is True
            assert observation["status"] == "OBSERVED"
            assert observation["validity"] == "POINT_IN_TIME_ONLY"
            assert observation["runtime_generation"] is None
            assert datetime.fromisoformat(observation["observed_at"]).tzinfo is not None
        # No polling or claim of freshness after an external reload.
        providers.models = [{"name": "reloaded-outside-rm"}]
        calls = list(providers.calls)
        assert gpu.evidence_snapshot()["MODEL_UNLOADED"] == models
        assert providers.calls == calls
        # A restarted RM does not inherit observations from a marker's absence.
        restarted = GPUResidency(gpu.ollama, gpu.comfy, gpu.marker)
        assert assert_unproven(restarted)["ollama"]["status"] == "NOT_OBSERVED"


INVALID = [
    ("ollama", "/api/ps", None),
    ("ollama", "/api/ps", {}),
    ("ollama", "/api/ps", {"models": None}),
    ("ollama", "/api/ps", {"models": [None]}),
    ("comfyui", "/ai-platform/residency", {"loaded_models": 0}),
    *[("comfyui", "/ai-platform/residency", {
        "schema_version": 1, "loaded_models": 0, "cleanup_pending": False,
        "queue_running": 0, "queue_pending": 0, key: value,
    }) for key, value in [("schema_version", True), ("loaded_models", False),
                         ("loaded_models", -1), ("cleanup_pending", 0),
                         ("queue_running", False)]],
]


@pytest.mark.anyio
@pytest.mark.parametrize("runtime,path,payload", INVALID)
async def test_malformed_evidence_cannot_preserve_positive_fact(tmp_path, runtime, path, payload):
    providers = Providers()
    providers.models = []
    invalid = False

    def handle(request):
        return httpx.Response(200, content=json.dumps(payload)) if invalid else providers.handle(request)

    async with residency(tmp_path, handle) as gpu:
        await gpu._json(gpu.ollama, path)
        assert assert_unproven(gpu)[runtime]["models_unloaded"] is True
        invalid = True
        await gpu._json(gpu.ollama, path)
        observation = assert_unproven(gpu)[runtime]
        assert observation["status"] == "UNKNOWN"
        assert observation["models_unloaded"] is None


@pytest.mark.anyio
@pytest.mark.parametrize("failure", ["http", "transport", "json", "cancel"])
async def test_lost_evidence_cannot_preserve_positive_fact(tmp_path, failure):
    fail = False

    def handle(request):
        if not fail:
            return httpx.Response(200, json={"models": []})
        if failure == "transport":
            raise httpx.ConnectError("unavailable")
        if failure == "cancel":
            raise asyncio.CancelledError()
        return httpx.Response(500) if failure == "http" else httpx.Response(200, text="{")

    async with residency(tmp_path, handle) as gpu:
        await gpu._json(gpu.ollama, "/api/ps")
        fail = True
        with pytest.raises((httpx.HTTPError, ValueError, asyncio.CancelledError)):
            await gpu._json(gpu.ollama, "/api/ps")
        assert assert_unproven(gpu)["ollama"]["status"] == "UNKNOWN"
        assert assert_unproven(gpu)["ollama"]["models_unloaded"] is None


@pytest.mark.anyio
async def test_older_response_cannot_overwrite_newer_failed_read(tmp_path):
    entered, finish = asyncio.Event(), asyncio.Event()
    calls = 0

    async def handle(request):
        nonlocal calls
        calls += 1
        if calls == 1:
            entered.set()
            await finish.wait()
            return httpx.Response(200, json={"models": []})
        return httpx.Response(503)

    async with residency(tmp_path, handle) as gpu:
        older = asyncio.create_task(gpu._json(gpu.ollama, "/api/ps"))
        await entered.wait()
        assert assert_unproven(gpu)["ollama"]["status"] == "UNKNOWN"
        with pytest.raises(httpx.HTTPStatusError):
            await gpu._json(gpu.ollama, "/api/ps")
        finish.set()
        await older
        assert assert_unproven(gpu)["ollama"]["status"] == "UNKNOWN"


@pytest.mark.anyio
async def test_post_ack_memory_and_cleanup_flags_are_not_model_or_gpu_proof(tmp_path):
    providers = Providers()
    async with residency(tmp_path, providers.handle, require_comfy_extension=False) as gpu:
        await gpu.comfy.post("/free", json={"unload_models": True})
        await gpu.ollama.post("/api/generate", json={
            "model": "resident", "keep_alive": 0, "stream": False})
        await gpu._json(gpu.comfy, "/system_stats")
        assert await gpu._comfy_models_idle() is True  # legacy option
        gpu.cleanup_evidence = {"cpu_terminal_verified": True, "gpu_cleanup_attested": True,
                                "reserved_bytes": [0]}
        for state in ("llm", "media", "vision_cleaned", "blocked"):
            gpu.state = state
            assert all(o["status"] == "NOT_OBSERVED" for o in assert_unproven(gpu).values())


@pytest.mark.anyio
async def test_status_addition_health_compatibility_and_no_extra_io(tmp_path):
    providers = Providers()
    app = create_gateway_app(
        Settings(_env_file=None, gateway_gpu_marker=tmp_path / "api-marker"),
        upstream_transport=httpx.MockTransport(providers.handle),
        residency_transport=httpx.MockTransport(providers.handle),
    )
    async with api_client(app) as client:
        gpu = app.state.resource_leases.residency
        original = gpu.snapshot()
        before = list(providers.calls)
        status = (await client.get("/status")).json()
        assert providers.calls == before
        assert status["gpu_residency"] == original
        assert status["active_count"] == 0
        assert status["resource_evidence"] == gpu.evidence_snapshot()
        health = (await client.get("/health")).json()
        assert health["status"] == "ok" and health["ollama"] == "ok"
        assert health["gpu_residency"] == original
        assert "resource_evidence" not in health
        assert providers.calls == before + ["/api/tags"]
        assert assert_unproven(gpu)["ollama"]["status"] == "NOT_OBSERVED"
        # Raw provider fields and model names never enter new diagnostics.
        providers.models = [{"name": "PRIVATE_MODEL", "token": "PRIVATE_TOKEN"}]
        await gpu._json(gpu.ollama, "/api/ps")
        facts = gpu.evidence_snapshot()
        assert "PRIVATE_" not in json.dumps(facts)
        facts["MODEL_UNLOADED"]["ollama"]["status"] = "VERIFIED"
        assert assert_unproven(gpu)["ollama"]["status"] == "OBSERVED"
