"""N2 denial boundary tests. No hardware or trusted production adapter."""
import asyncio

import httpx
import pytest

from ai_bridge.gateway.app import create_gateway_app
from ai_bridge.gateway.integration import AdmissionNotVerified
from ai_bridge.gateway.resource_leases import ResourceLeaseRegistry, _Lease
from ai_bridge.gateway.scheduler import PriorityScheduler
from ai_bridge.settings import Settings
from test_gateway_priority_classes import PATHS, api_client
from test_accelerator_admission_n1 import configuration


@pytest.fixture
def anyio_backend():
    return "asyncio"


def app_for_test(monkeypatch, **settings):
    def forbidden(*args, **kwargs):
        pytest.fail("N2 must not construct a competing core or execute upstream")
    monkeypatch.setattr("ai_bridge.gateway.accelerator_admission.AcceleratorAdmission.__init__", forbidden)
    return create_gateway_app(
        Settings(_env_file=None, gateway_admission_strategy="n2-dev-blocked", **settings),
        upstream_transport=httpx.MockTransport(forbidden),
        residency_transport=httpx.MockTransport(forbidden),
        knowledge_runtime_factory=forbidden,
    )


@pytest.mark.anyio
@pytest.mark.parametrize("path", PATHS)
@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("leased", [False, True])
async def test_every_http_ingress_denied_before_upstream(monkeypatch, path, stream, leased):
    app = app_for_test(monkeypatch)
    async with api_client(app) as client:
        headers = {"x-ai-resource-lease": "old-or-forged"} if leased else {}
        response = await client.post(path, json={"stream": stream}, headers=headers)
        assert response.status_code == 503
        assert response.json()["verification"] == "NOT_VERIFIED"
        state = await app.state.scheduler.snapshot()
        assert state["active_count"] == state["queued_count"] == 0
        assert state["recent_jobs"] == []
        assert app.state.resource_leases.scheduler is app.state.scheduler


@pytest.mark.anyio
@pytest.mark.parametrize("path", PATHS)
async def test_denial_precedes_body_read_and_client_metadata(monkeypatch, path, caplog):
    from starlette.requests import Request

    app = app_for_test(monkeypatch)
    async with api_client(app) as client:
        async def forbidden_body(self):
            pytest.fail("blocked inference must not consume the request body")

        monkeypatch.setattr(Request, "body", forbidden_body)
        response = await client.post(path, content=b"invalid-json", headers={
            "x-ai-priority": "invalid", "x-ai-resource-lease": "old-or-forged",
        })
        assert response.status_code == 503
        assert response.json()["verification"] == "NOT_VERIFIED"
        state = await app.state.scheduler.snapshot()
        assert state["active_count"] == state["queued_count"] == 0
        assert state["recent_jobs"] == []
    assert "physical N1 grants NOT_ADMITTED" in caplog.text


@pytest.mark.anyio
async def test_reservation_external_media_and_cleanup_cannot_bypass(monkeypatch):
    app = app_for_test(monkeypatch)
    async with api_client(app) as client:
        for profile in ("external", "llm", "embeddings", "media-image", "media-video"):
            assert (await client.post("/resource/leases", json={"workload": profile})).status_code == 503
        leases = app.state.resource_leases
        # Simulate an old/stranded lease; never infer cleanup from its TTL.
        rec = _Lease("old", 1, 10, "synthetic", 0, 0, external_use_id="use")
        leases._leases["old"] = rec
        response = await client.post("/resource/leases/old/uses", json={
            "provider": "comfyui-local", "capability": "video-generation"})
        assert response.status_code == 503
        assert (await client.get("/resource/leases/old/uses/use")).status_code == 503
        assert (await client.delete("/resource/leases/old/uses/use")).status_code == 503
        assert (await client.delete("/resource/leases/old")).status_code == 503
        assert await leases.reap_expired() == 0
        assert leases._leases["old"] is rec and rec.external_use_id == "use"
        rec.external_use_id = None
        assert await leases.reap_expired() == 0
        assert leases._leases["old"] is rec


@pytest.mark.anyio
async def test_platform_generation_uses_same_denial(monkeypatch):
    app = app_for_test(monkeypatch)
    async with api_client(app) as client:
        response = await client.post("/api/v1/ai", json={"messages": [{"role": "user", "content": "test"}]})
        assert response.status_code == 503
        assert "accelerator_admission_not_verified" in response.text
        assert (await app.state.scheduler.snapshot())["active_count"] == 0


@pytest.mark.anyio
async def test_restart_and_residency_cannot_open_boundary(monkeypatch):
    for _ in range(2):
        app = app_for_test(monkeypatch)
        async with api_client(app) as client:
            scheduler = app.state.scheduler
            scheduler.admission_blocked = False
            scheduler._dispatch_locked()
            assert scheduler.admission_blocked
            state = (await client.get("/status")).json()
            boundary = state["accelerator_admission"]
            assert boundary["verification"] == "NOT_VERIFIED"
            assert not boundary["execution_enabled"] and not boundary["n1_core_started"]
            assert boundary["devices"]["local-primary"]["ownership"] == "UNKNOWN"
            assert (await client.post("/api/chat", json={})).status_code == 503


@pytest.mark.anyio
async def test_scheduler_primitives_deny_without_mutation():
    scheduler = PriorityScheduler(admission_strategy="n2-dev-blocked")
    leases = ResourceLeaseRegistry(scheduler)
    calls = [scheduler.acquire(priority=1, source="test"),
             scheduler.reserve(priority=1, source="test"), scheduler.active_ticket(1),
             scheduler.mark_running(1), scheduler.release_job(1),
             leases.begin_use("old"), leases.end_use("old", release=True)]
    for call in calls:
        with pytest.raises(AdmissionNotVerified):
            await call
    async with asyncio.timeout(1):
        with pytest.raises(AdmissionNotVerified):
            async with scheduler.slot(priority=1, source="test"):
                pytest.fail("execution bypass")
    assert not (await scheduler.snapshot())["recent_jobs"]


@pytest.mark.anyio
async def test_synthetic_inventory_is_not_trusted_execution_proof():
    registry, _ = configuration(2)
    scheduler = PriorityScheduler(admission_strategy="n2-dev-blocked", accelerator_registry=registry)
    state = (await scheduler.snapshot())["accelerator_admission"]
    assert set(state["devices"]) == {"gpu-0", "gpu-1"}
    assert all(row["shared_owners"] is None for row in state["devices"].values())
    with pytest.raises(AdmissionNotVerified):
        await scheduler.acquire(priority=1, source="test")


@pytest.mark.parametrize("mode", ["n1", "shared", "production", "", True])
def test_unknown_strategy_rejected(mode):
    with pytest.raises(ValueError):
        Settings(_env_file=None, gateway_admission_strategy=mode)
    with pytest.raises(ValueError):
        PriorityScheduler(admission_strategy=mode)


@pytest.mark.anyio
@pytest.mark.parametrize("explicit", [False, True])
async def test_disabled_keeps_legacy_wire_and_streaming(explicit):
    async def content():
        yield b'{"done":true}\n'
    settings = {"gateway_admission_strategy": "legacy"} if explicit else {}
    app = create_gateway_app(Settings(_env_file=None, **settings),
                             upstream_transport=httpx.MockTransport(lambda r: httpx.Response(200, content=content())))
    async with api_client(app) as client:
        for stream in (False, True):
            response = await client.post("/api/chat", json={"stream": stream})
            assert response.status_code == 200 and response.content == b'{"done":true}\n'
            assert "x-ai-job-id" in response.headers
        status = (await client.get("/status")).json()
        assert "accelerator_admission" not in status
        assert status["active_count"] == status["queued_count"] == 0
        assert all(job["state"] == "completed" for job in status["recent_jobs"])


@pytest.mark.anyio
@pytest.mark.parametrize("route", ["search", "ask"])
async def test_retrieval_cannot_escape_to_another_gateway(monkeypatch, route):
    app = app_for_test(monkeypatch)
    async with api_client(app) as client:
        response = await client.post(f"/api/v1/knowledge/{route}", json={"query": "test", "mode": "hybrid"})
        assert response.status_code == 503
        assert "accelerator_admission_not_verified" in response.text


@pytest.mark.parametrize("mutation", ["unknown-provider", "unknown-device", "node-mismatch"])
def test_n2_revalidates_inventory_binding(mutation):
    from ai_bridge.providers.registry import NodeDescriptor, local_descriptor_registry
    registry, _ = configuration()
    providers = local_descriptor_registry()
    binding = registry.provider_bindings[0]
    if mutation == "unknown-provider":
        binding = binding.model_copy(update={"provider_id": "missing"})
    elif mutation == "unknown-device":
        binding = binding.model_copy(update={"accelerator_ids": ("missing",)})
    else:
        providers = providers.model_copy(update={"nodes": (*providers.nodes, NodeDescriptor(node_id="other"))})
        registry = registry.model_copy(update={"accelerators": (
            registry.accelerators[0].model_copy(update={"node_id": "other"}),)})
    registry = registry.model_copy(update={"provider_bindings": (binding,)})
    with pytest.raises(ValueError):
        PriorityScheduler(admission_strategy="n2-dev-blocked", registry=providers, accelerator_registry=registry)
