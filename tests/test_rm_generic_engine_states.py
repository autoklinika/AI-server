"""CPU-only derived diagnostics; no runtime or GPU grants."""
from dataclasses import FrozenInstanceError
import json

import httpx
import pytest

from ai_bridge.gateway.app import create_gateway_app
from ai_bridge.gateway.engine_state import (
    DEFAULT_ENGINES, EngineDescriptor, EngineRegistry, ResourceState,
    resource_manager_snapshot,
)
from ai_bridge.gateway.jobs import JobMetadata
from ai_bridge.gateway.admission import external_workload
from ai_bridge.settings import Settings
from test_gateway_priority_classes import api_client
from test_gpu_residency import Providers


@pytest.fixture
def anyio_backend():
    return "asyncio"


def snapshots(state="llm", providers=()):
    active = [{"job": {"state": "admitted", "workload": [
        {"provider": provider, "node": "local", "capability": "chat"}
        for provider in providers]}}] if providers else []
    return ({"active_count": len(active), "active": active,
             "queued_count": 0, "admission_blocked": False},
            {"state": state, "recovery_required": state == "blocked"})


@pytest.mark.parametrize("legacy,providers,state,owner,target", [
    ("llm", (), "IDLE", None, None),
    ("llm", ("ollama-local",), "RUNNING", "ollama", None),
    ("llm", ("ollama-local", "comfyui-local"), "RUNNING", None, None),
    ("media", ("ollama-local", "comfyui-local"), "RUNNING", "comfyui", None),
    ("draining_ollama", ("comfyui-local",), "SWITCHING", "ollama", "comfyui"),
    ("freeing_comfy", ("comfyui-local",), "SWITCHING", "comfyui", "ollama"),
    ("media", (), "BLOCKED", None, None),
    ("media", ("ollama-local",), "BLOCKED", None, None),
    ("blocked", (), "BLOCKED", None, None),
    ("future-state", (), "BLOCKED", None, None),
    ("llm", ("vision-local",), "BLOCKED", None, None),
    ("llm", ("unknown-local",), "BLOCKED", None, None),
])
def test_mapping(legacy, providers, state, owner, target):
    view = resource_manager_snapshot(*snapshots(legacy, providers))
    assert (view["state"], view["active_engine"], view["target_engine"]) == (state, owner, target)


@pytest.mark.parametrize("field,value", [
    ("active_count", True), ("active_count", -1), ("active_count", 2),
    ("active", None), ("active", [{}]), ("queued_count", None),
    ("admission_blocked", None), ("admission_blocked", True),
])
def test_invalid_scheduler_blocks(field, value):
    scheduler, residency = snapshots()
    scheduler[field] = value
    assert resource_manager_snapshot(scheduler, residency)["state"] == "BLOCKED"


def test_incomplete_and_multiple_owners_block():
    for scheduler, residency in [(None, {}), ({}, {}), ({}, None)]:
        assert resource_manager_snapshot(scheduler, residency)["state"] == "BLOCKED"
    scheduler, residency = snapshots("llm", ("ollama-local",))
    for key in list(scheduler):
        assert resource_manager_snapshot({k: v for k, v in scheduler.items() if k != key}, residency)["state"] == "BLOCKED"
    for key in list(residency):
        assert resource_manager_snapshot(scheduler, {k: v for k, v in residency.items() if k != key})["state"] == "BLOCKED"
    scheduler["active"] *= 2
    scheduler["active_count"] = 2
    assert resource_manager_snapshot(scheduler, residency)["reason"] == "multiple_active_tickets"


@pytest.mark.parametrize("job", [None, {}, {"state": "completed", "workload": []},
    {"state": "running", "workload": []}, {"state": "running", "workload": [None]},
    {"state": "running", "workload": [{"provider": "ollama-local"}]}])
def test_incomplete_active_metadata_blocks(job):
    scheduler, residency = snapshots("llm", ("ollama-local",))
    scheduler["active"][0]["job"] = job
    assert resource_manager_snapshot(scheduler, residency)["state"] == "BLOCKED"


def test_in_process_tuple_workload_preserves_real_owner():
    # Dataclass asdict leaves workload tuple-shaped; HTTP serialization
    # later turns it into a list. Both inputs must have identical semantics.
    sched, resident = snapshots("media", ("ollama-local", "comfyui-local"))
    sched["active"][0]["job"]["workload"] = tuple(
        sched["active"][0]["job"]["workload"])
    view = resource_manager_snapshot(sched, resident)
    assert view["state"] == "RUNNING"
    assert view["active_engine"] == "comfyui"


def test_waiters_do_not_own_resource_and_private_data_is_ignored():
    scheduler, residency = snapshots()
    scheduler.update(queued_count=5, token="SECRET", lease_id="SECRET", source="SECRET")
    residency["cleanup_evidence"] = {"token": "SECRET"}
    view = resource_manager_snapshot(scheduler, residency)
    assert view["state"] == "IDLE"
    assert "SECRET" not in json.dumps(view)


def test_registry_extends_without_states_or_shared_mutation():
    extra = EngineDescriptor("future", "future-local", "not_installed", False)
    supplied = [*DEFAULT_ENGINES.engines, extra]
    registry = EngineRegistry(supplied)
    supplied.clear()
    view = resource_manager_snapshot(*snapshots(), registry)
    assert len(view["engines"]) == 4
    assert set(ResourceState) == {"IDLE", "RUNNING", "SWITCHING", "BLOCKED"}
    assert view["engines"][2] == {"id": "vision", "provider_id": "vision-local",
                                  "status": "not_installed", "execution_available": False}
    view["engines"][2]["execution_available"] = True
    view["engines"].clear()
    assert registry.snapshot()[2]["execution_available"] is False
    assert resource_manager_snapshot(*snapshots(), registry)["state"] == "IDLE"
    with pytest.raises(FrozenInstanceError):
        extra.status = "configured"


@pytest.mark.parametrize("args", [
    ("BAD", "local", "configured", True), ("ok", "bad/id", "configured", True),
    ("ok", "local", "ready", True), ("ok", "local", "configured", 1),
    ("ok", "local", "not_installed", True), (None, "local", "configured", True),
])
def test_invalid_descriptors(args):
    with pytest.raises(ValueError):
        EngineDescriptor(*args)


def test_duplicate_and_invalid_registries():
    first = DEFAULT_ENGINES.engines[0]
    for entries in [(), ({},), (first, first),
                    (first, EngineDescriptor("other", first.provider_id, "configured", True))]:
        with pytest.raises(ValueError):
            EngineRegistry(entries)


@pytest.mark.anyio
async def test_http_same_view_no_extra_io_and_no_admission_changes(tmp_path):
    providers = Providers()
    app = create_gateway_app(
        Settings(_env_file=None, gateway_gpu_marker=tmp_path / "marker"),
        upstream_transport=httpx.MockTransport(providers.handle),
        residency_transport=httpx.MockTransport(providers.handle),
    )
    async with api_client(app) as client:
        leases = app.state.resource_leases
        scheduler = leases.scheduler
        gpu = leases.residency
        for legacy in ("llm", "media", "draining_ollama", "freeing_comfy", "blocked"):
            lease = await leases.create(priority=50, source="PRIVATE", metadata=JobMetadata(
                capability="external-reservation", workload=external_workload(scheduler.registry)))
            gpu.state = legacy
            before = list(providers.calls)
            original = gpu.snapshot()
            status = (await client.get("/status", headers={"x-engine": "vision"})).json()
            assert providers.calls == before
            health = (await client.get("/health")).json()
            assert providers.calls == before + ["/api/tags"]
            assert status["resource_manager"] == health["resource_manager"]
            assert status["resource_manager"] == resource_manager_snapshot(await scheduler.snapshot(), original)
            assert status["gpu_residency"] == health["gpu_residency"] == original
            assert "PRIVATE" not in json.dumps(status["resource_manager"])
            assert lease["lease_id"] not in json.dumps(status["resource_manager"])
            assert scheduler.admission_blocked is False
            assert gpu.evidence_snapshot()["GPU_REUSE_SAFE"]["status"] == "NOT_VERIFIED"
            gpu.state = "llm"
            await leases.release(lease["lease_id"])
