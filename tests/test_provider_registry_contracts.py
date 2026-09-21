"""D.3 inventory contracts and assignment; no backend/network calls."""
import asyncio
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from ai_bridge.gateway.jobs import JobMetadata
from ai_bridge.gateway.scheduler import PriorityScheduler
from ai_bridge.providers.registry import (
    CapabilityDescriptor, DescriptorRegistry, LogicalProviderDescriptor,
    NodeDescriptor, local_descriptor_registry,
)
from ai_bridge.settings import Settings
from test_gateway_priority_classes import PATHS, api_client, make_app


@pytest.fixture
def anyio_backend():
    return "asyncio"


def test_baseline_roundtrip_and_immutable_snapshot():
    registry = local_descriptor_registry()
    assert {p.provider_id: p.provider_type for p in registry.providers} == {
        "ollama-local": "llm", "comfyui-local": "media-generation", "hermes-local": "agent",
    }
    assert [n.node_id for n in registry.nodes] == ["ai-node-01"]
    assert all(p.node_id == "ai-node-01" for p in registry.providers)
    assert DescriptorRegistry.model_validate_json(registry.model_dump_json()) == registry
    snapshot = registry.snapshot()
    snapshot["providers"][0]["capabilities"].clear()
    assert registry.provider("ollama-local").capabilities
    with pytest.raises(ValidationError):
        registry.nodes[0].node_id = "changed"
    assert all("status" not in p and "models" not in p and "metadata" not in p
               for p in registry.snapshot()["providers"])


@pytest.mark.parametrize("value", [None, "", " ", " bad", "bad\n", "node/name", "http://host", 42, True, [], "a" * 129])
@pytest.mark.parametrize("kind", ["node", "provider", "capability"])
def test_invalid_descriptor_ids(kind, value):
    with pytest.raises(ValidationError):
        if kind == "node":
            NodeDescriptor(node_id=value)
        elif kind == "capability":
            CapabilityDescriptor(capability_id=value, provider_types=("llm",))
        else:
            LogicalProviderDescriptor(provider_id=value, provider_type="llm",
                                      node_id="node", capabilities=("chat",))


@pytest.mark.parametrize("collection", ["nodes", "providers", "capabilities"])
@pytest.mark.parametrize("defect", ["empty", "duplicate", "extra"])
def test_invalid_collections(collection, defect):
    data = local_descriptor_registry().snapshot()
    if defect == "empty":
        data[collection] = []
    elif defect == "duplicate":
        data[collection].append(data[collection][0])
    else:
        data[collection][0]["unexpected"] = "not-allowed"
    with pytest.raises(ValidationError):
        DescriptorRegistry.model_validate(data)


@pytest.mark.parametrize("field,value", [
    ("node_id", "absent"), ("provider_type", "absent"),
    ("provider_type", "agent"), ("capabilities", ["absent"]),
    ("capabilities", []), ("capabilities", ["chat", "chat"]),
    ("capabilities", ["video-generation"]), ("capabilities", ["external-reservation"]),
])
def test_invalid_provider_references(field, value):
    data = local_descriptor_registry().snapshot()
    data["providers"][0][field] = value
    with pytest.raises(ValidationError):
        DescriptorRegistry.model_validate(data)


@pytest.mark.parametrize("version", [0, 2, True, 1.0, "1", None])
def test_invalid_registry_version(version):
    data = local_descriptor_registry().snapshot()
    data["schema_version"] = version
    with pytest.raises(ValidationError):
        DescriptorRegistry.model_validate(data)


def test_invalid_capability_types():
    for types in [("llm", "llm"), ("absent",)]:
        with pytest.raises(ValidationError):
            CapabilityDescriptor(capability_id="chat", provider_types=types)


def test_checked_in_config_matches_packaged_defaults_and_order_is_irrelevant():
    path = Path(__file__).resolve().parents[1] / "deploy/gateway-registry.example.json"
    registry = DescriptorRegistry.model_validate_json(path.read_text())
    assert registry == local_descriptor_registry()
    data = registry.snapshot()
    for key in ("providers", "capabilities", "nodes"):
        data[key].reverse()
    for provider in data["providers"]:
        provider["capabilities"].reverse()
    for capability in data["capabilities"]:
        capability["provider_types"].reverse()
    make_app(gateway_registry=data)


def test_invalid_config_through_settings_has_no_silent_fallback(monkeypatch):
    data = local_descriptor_registry().snapshot()
    data["providers"][0]["node_id"] = "missing-node"
    monkeypatch.setenv("AI_BRIDGE_GATEWAY_REGISTRY", json.dumps(data))
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


@pytest.mark.parametrize("lookup", ["node", "provider", "capability"])
def test_unknown_lookup_errors_do_not_echo_input(lookup):
    with pytest.raises(ValueError) as error:
        getattr(local_descriptor_registry(), lookup)("PRIVATE_REQUEST_CONTENT")
    assert "PRIVATE_REQUEST_CONTENT" not in str(error.value)


def test_explicit_json_config_and_local_node_identity(monkeypatch):
    registry = local_descriptor_registry("test-node")
    monkeypatch.setenv("AI_BRIDGE_GATEWAY_REGISTRY", registry.model_dump_json())
    settings = Settings(_env_file=None, node_id="test-node")
    assert settings.gateway_registry == registry
    make_app(node_id="test-node")
    with pytest.raises(ValueError, match="single-node"):
        make_app(node_id="other-node")


@pytest.mark.parametrize("change", ["remote", "missing-provider", "renamed-provider", "missing-capability"])
def test_gateway_rejects_topology_changes_before_runtime(change):
    data = local_descriptor_registry().snapshot()
    if change == "remote":
        data["nodes"].append({"node_id": "future-node"})
        data["providers"][0]["node_id"] = "future-node"
    elif change == "missing-provider":
        data["providers"].pop()
    elif change == "renamed-provider":
        data["providers"][0]["provider_id"] = "other-llm"
    else:
        data["providers"][0]["capabilities"].remove("chat")
    registry = DescriptorRegistry.model_validate(data)  # structurally valid inventory
    with pytest.raises(ValueError, match="D.3 gateway"):
        make_app(gateway_registry=registry)


@pytest.mark.anyio
async def test_invalid_assignments_are_atomic_and_do_not_leak_slot():
    scheduler = PriorityScheduler()
    ticket = await scheduler.acquire(priority=50, source="test", metadata=JobMetadata(capability="chat"))
    before = await scheduler.job_status(ticket.job_id)
    for provider, node in [("absent", "ai-node-01"), ("ollama-local", "absent"),
                           ("hermes-local", "ai-node-01"), (None, "ai-node-01"),
                           ("ollama-local", None)]:
        with pytest.raises(ValueError):
            await scheduler.mark_running(ticket.job_id, provider=provider, node=node)
        assert await scheduler.job_status(ticket.job_id) == before
    await scheduler.mark_running(ticket.job_id, provider="ollama-local", node="ai-node-01")
    await scheduler.release(ticket)
    assert (await scheduler.snapshot())["active_count"] == 0
    with pytest.raises(ValueError, match="unknown capability"):
        await scheduler.acquire(priority=50, source="test", metadata=JobMetadata(capability="absent"))
    assert len((await scheduler.snapshot())["recent_jobs"]) == 1


def test_multi_node_descriptor_has_unambiguous_assignment_but_no_execution():
    data = local_descriptor_registry().snapshot()
    data["nodes"].append({"node_id": "future-node"})
    data["providers"][0]["node_id"] = "future-node"
    registry = DescriptorRegistry.model_validate(data)
    with pytest.raises(ValueError, match="node mismatch"):
        registry.validate_assignment("ollama-local", "ai-node-01", "chat")
    assert registry.validate_assignment("ollama-local", "future-node", "chat").node_id == "future-node"


@pytest.mark.parametrize("path", PATHS)
@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.anyio
async def test_http_assignment_matches_registry_and_preserves_payload(path, stream, caplog):
    app = None
    secret = "PRIVATE_PROMPT_NOT_IN_REGISTRY_OR_JOBS"
    body = json.dumps({"model": "unchanged-model", "messages": [{"content": secret}], "stream": stream}).encode()

    async def handler(request):
        assert request.content == body
        state = (await app.state.scheduler.snapshot())["active"][0]["job"]
        assert state["state"] == "running"
        descriptor = app.state.descriptor_registry.validate_assignment(
            state["assigned_provider"], state["assigned_node"], state["capability"])
        assert descriptor.provider_id == "ollama-local"
        async def content():
            yield b'{"ok":true}\n'
        return httpx.Response(200, content=content())

    app = make_app(handler, node_id="test-node")
    async with api_client(app) as client:
        response = await client.post(path, content=body)
        assert response.status_code == 200
        status = (await client.get("/status")).json()
        assert status["registry"]["nodes"] == [{"node_id": "test-node"}]
        assert status["recent_jobs"][-1]["assigned_node"] == "test-node"
        assert secret not in json.dumps(status) + caplog.text


@pytest.mark.anyio
async def test_queue_and_external_lease_do_not_claim_provider_assignment():
    app = make_app()
    async with api_client(app) as client:
        lease = (await client.post("/resource/leases", json={"source": "comfyui-local"})).json()
        pending = asyncio.create_task(client.post("/api/chat", json={}))
        try:
            for _ in range(100):
                status = (await client.get("/status")).json()
                if status["queued_count"]:
                    break
                await asyncio.sleep(0)
            assert status["queued_count"] == 1
            for item in status["active"] + status["queued"]:
                assert item["job"]["assigned_provider"] is None
                assert item["job"]["assigned_node"] is None
            assert (await client.post("/api/chat", json={}, headers={
                "X-AI-Resource-Lease": lease["lease_id"],
            })).status_code == 200
            active = (await client.get("/status")).json()["active"][0]["job"]
            assert active["state"] == "admitted"
            assert active["assigned_provider"] is active["assigned_node"] is None
        finally:
            await client.delete(f"/resource/leases/{lease['lease_id']}")
            await pending
