"""P2-A CPU-only, opt-in shadow integration. No physical GPU access."""

from __future__ import annotations

import asyncio
from dataclasses import replace

import httpx
import pytest

from ai_bridge.gateway.app import create_gateway_app
from ai_bridge.gateway.resource_accounting import (
    AssessmentClock,
    Demand,
    DeviceRequest,
    MemoryObservation,
    Observation,
    ResourceRequest,
    ResourceSnapshot,
)
from ai_bridge.gateway.resource_shadow import ShadowInputs, observe_shadow
from ai_bridge.providers.accelerators import AcceleratorDescriptor, AcceleratorRegistry
from ai_bridge.providers.resource_topology import Device, MemoryDomain, ResourceTopology
from ai_bridge.settings import Settings

GIB = 1024**3


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _changed(model, **fields):
    return type(model).model_validate({**model.model_dump(), **fields})


def _evidence(selected: str = "rtx-b") -> ShadowInputs:
    devices = (
        Device(
            logical_id="radeon",
            physical_id="gpu-amd-stable",
            generation=2,
            node_id="node-1",
            backend="vulkan",
            runtime_id="vulkan-runtime",
            ordinal=0,
            memory_class="unified",
            memory_domain_id="host",
        ),
        Device(
            logical_id="rtx-a",
            physical_id="gpu-nvidia-a-stable",
            generation=3,
            node_id="node-1",
            backend="cuda",
            runtime_id="cuda-runtime",
            ordinal=0,
            memory_class="dedicated",
            memory_domain_id="vram-a",
        ),
        Device(
            logical_id="rtx-b",
            physical_id="gpu-nvidia-b-stable",
            generation=4,
            node_id="node-1",
            backend="cuda",
            runtime_id="cuda-runtime",
            ordinal=1,
            memory_class="dedicated",
            memory_domain_id="vram-b",
        ),
    )
    domains = (
        MemoryDomain(
            domain_id="host",
            node_id="node-1",
            kind="host",
            generation=1,
            total_bytes=96 * GIB,
            system_reserved_bytes=8 * GIB,
        ),
        MemoryDomain(
            domain_id="vram-a",
            node_id="node-1",
            kind="dedicated",
            generation=1,
            total_bytes=16 * GIB,
            system_reserved_bytes=GIB,
        ),
        MemoryDomain(
            domain_id="vram-b",
            node_id="node-1",
            kind="dedicated",
            generation=1,
            total_bytes=48 * GIB,
            system_reserved_bytes=2 * GIB,
        ),
    )
    topology = ResourceTopology(revision=7, devices=devices, domains=domains)
    registry = AcceleratorRegistry(
        accelerators=tuple(
            AcceleratorDescriptor(
                accelerator_id=device.logical_id,
                node_id=device.node_id,
                kind="integrated" if device.memory_class == "unified" else "discrete",
                backend=device.backend,
                memory_class=device.memory_class,
                total_memory_bytes=next(
                    domain.total_bytes
                    for domain in domains
                    if domain.domain_id == device.memory_domain_id
                ),
                workload_classes=("llm",),
            )
            for device in devices
        )
    )
    snapshot = ResourceSnapshot(
        revision=6,
        topology_revision=7,
        epoch="boot-one",
        devices=tuple(
            Observation(
                resource_id=d.logical_id,
                generation=d.generation,
                epoch="boot-one",
                observed_at_ns=1000,
                health="healthy",
            )
            for d in devices
        ),
        memory=tuple(
            MemoryObservation(
                resource_id=d.domain_id,
                generation=d.generation,
                epoch="boot-one",
                observed_at_ns=1000,
                health="healthy",
                observed_used_bytes=0,
                attributed=(),
            )
            for d in domains
        ),
        faults=(),
        commitments=(),
    )
    current = next(d for d in devices if d.logical_id == selected)
    request = ResourceRequest(
        node_id="node-1",
        expected_revision=6,
        topology_revision=7,
        epoch="boot-one",
        devices=(
            DeviceRequest(
                logical_id=current.logical_id,
                physical_id=current.physical_id,
                generation=current.generation,
                backend=current.backend,
                runtime_id=current.runtime_id,
            ),
        ),
        demands=(
            Demand(
                allocation_id="new-workload",
                domain_id=current.memory_domain_id,
                bytes=GIB,
            ),
        ),
    )
    clock = AssessmentClock(epoch="boot-one", now_ns=1010, max_age_ns=100)
    return ShadowInputs(
        topology=topology,
        registry=registry,
        snapshot=snapshot,
        request=request,
        clock=clock,
    )


def _gateway(tmp_path, *, enabled: bool = False, source=None):
    def upstream(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"models": []}, request=request)

    return create_gateway_app(
        Settings(
            _env_file=None,
            gateway_resource_shadow_enabled=enabled,
            gateway_gpu_marker=tmp_path / "gpu.blocked",
            gateway_max_concurrency=1,
        ),
        upstream_transport=httpx.MockTransport(upstream),
        resource_shadow_source=source,
    )


@pytest.mark.anyio
async def test_default_off_keeps_status_shape_and_never_evaluates(tmp_path):
    called = []

    def forbidden():
        called.append("called")
        raise AssertionError("disabled shadow adapter was called")

    app = _gateway(tmp_path, source=forbidden)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            status = (await client.get("/status")).json()
            health = (await client.get("/health")).json()
            assert "resource_shadow" not in status
            assert "resource_shadow" not in health
            assert status["active_count"] == 0
            assert status["resource_leases"]["lease_count"] == 0
            assert not called


@pytest.mark.anyio
async def test_enabled_without_evidence_is_unknown_not_a_grant(tmp_path):
    app = _gateway(tmp_path, enabled=True)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            status = (await client.get("/status")).json()
            assert status["resource_shadow"] == {
                "mode": "observation",
                "result": "UNKNOWN",
                "reason_codes": ["missing_evidence"],
                "authorizes_execution": False,
            }
            assert status["active_count"] == 0
            assert status["resource_manager"]["state"] == "IDLE"
            assert "resource_shadow" not in (await client.get("/health")).json()


@pytest.mark.anyio
async def test_enabled_fit_is_only_a_diagnostic_and_legacy_lease_works(tmp_path):
    inputs = _evidence()
    before = inputs.snapshot.model_dump()
    app = _gateway(tmp_path, enabled=True, source=lambda: inputs)

    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            status = (await client.get("/status")).json()
            shadow = status["resource_shadow"]
            assert shadow == {
                "mode": "observation",
                "result": "FIT",
                "reason_codes": [],
                "authorizes_execution": False,
            }
            assert "rtx-b" not in str(shadow)
            assert "gpu-nvidia-b-stable" not in str(shadow)
            assert status["active_count"] == 0

            # Only the EXISTING scheduler may actually reserve a slot.
            lease = await client.post(
                "/resource/leases", json={"source": "shadow-regression", "priority": 50}
            )
            assert lease.status_code == 201
            active = (await client.get("/status")).json()
            assert active["active_count"] == 1
            assert active["resource_shadow"] == shadow
            assert (
                await client.delete(f"/resource/leases/{lease.json()['lease_id']}")
            ).json()["released"] is True
            assert (await client.get("/status")).json()["active_count"] == 0

    assert inputs.snapshot.model_dump() == before


@pytest.mark.parametrize("selected", ["radeon", "rtx-a", "rtx-b"])
def test_three_devices_have_separate_diagnostic_fit(selected):
    assert observe_shadow(lambda: _evidence(selected))["result"] == "FIT"


def test_insufficient_dedicated_vram_denies_instead_of_pooling_cards():
    values = _evidence("rtx-a")
    impossible = _changed(
        values.request.demands[0],
        bytes=17 * GIB,
    )
    result = observe_shadow(
        lambda: replace(
            values,
            request=_changed(values.request, demands=(impossible,)),
        )
    )
    assert result["result"] == "DENY"
    assert result["reason_codes"] == ["insufficient_capacity"]
    assert not result["authorizes_execution"]


def test_independent_gpu_b_is_not_denied_by_quarantined_gpu_a():
    values = _evidence("rtx-b")
    samples = tuple(
        _changed(sample, health="quarantined")
        if sample.resource_id == "rtx-a"
        else sample
        for sample in values.snapshot.devices
    )
    changed = replace(values, snapshot=_changed(values.snapshot, devices=samples))
    assert observe_shadow(lambda: changed)["result"] == "FIT"

    a = _evidence("rtx-a")
    rejected = replace(a, snapshot=_changed(a.snapshot, devices=samples))
    result = observe_shadow(lambda: rejected)
    assert result["result"] == "DENY"
    assert result["reason_codes"] == ["unhealthy"]


@pytest.mark.parametrize(
    "mutation,expected_code",
    [
        ("generation", "generation"),
        ("epoch", "clock_epoch"),
        ("stale", "stale"),
        ("future", "future"),
        ("missing", "missing_telemetry"),
        ("revision", "revision"),
    ],
)
def test_missing_stale_or_mismatched_evidence_is_unknown(mutation, expected_code):
    values = _evidence()
    if mutation == "generation":
        request = _changed(
            values.request,
            devices=(_changed(values.request.devices[0], generation=9),),
        )
        values = replace(values, request=request)
    elif mutation == "epoch":
        values = replace(values, clock=_changed(values.clock, epoch="after-restart"))
    elif mutation in ("stale", "future"):
        when = 1 if mutation == "stale" else 2000
        samples = tuple(
            _changed(sample, observed_at_ns=when)
            if sample.resource_id == "rtx-b"
            else sample
            for sample in values.snapshot.devices
        )
        values = replace(
            values,
            snapshot=_changed(values.snapshot, devices=samples),
        )
    elif mutation == "missing":
        samples = tuple(
            sample
            for sample in values.snapshot.memory
            if sample.resource_id != "vram-b"
        )
        values = replace(values, snapshot=_changed(values.snapshot, memory=samples))
    else:
        values = replace(
            values,
            request=_changed(values.request, expected_revision=999),
        )
    result = observe_shadow(lambda: values)
    assert result["result"] == "UNKNOWN"
    assert expected_code in result["reason_codes"]
    assert result["authorizes_execution"] is False


@pytest.mark.parametrize("failure", ["missing", "invalid", "raises"])
def test_broken_supplier_cannot_reach_rm_or_leak_exception(failure):
    def source():
        if failure == "missing":
            return None
        if failure == "invalid":
            return "fake-evidence"
        raise RuntimeError("private-credential-should-never-be-rendered")

    expected = "observer_error" if failure == "raises" else "missing_evidence"
    value = observe_shadow(source)
    assert value["result"] == "UNKNOWN"
    assert value["reason_codes"] == [expected]
    assert value["authorizes_execution"] is False
    assert "private-credential" not in str(value)


def test_cancelled_shadow_supplier_is_not_misclassified_as_normal_unknown():
    def cancel():
        raise asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        observe_shadow(cancel)


@pytest.mark.anyio
async def test_many_status_requests_cannot_change_scheduler_or_health(tmp_path):
    values = _evidence()
    app = _gateway(tmp_path, enabled=True, source=lambda: values)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            baseline = (await client.get("/status")).json()
            responses = await asyncio.gather(
                *(client.get("/status") for _ in range(12))
            )
            assert all(r.status_code == 200 for r in responses)
            assert all(
                r.json()["resource_shadow"]["result"] == "FIT" for r in responses
            )
            after = (await client.get("/status")).json()
            for key in (
                "active_count",
                "queued_count",
                "gpu_residency",
                "resource_manager",
            ):
                assert after[key] == baseline[key]
            assert "resource_shadow" not in (await client.get("/health")).json()


def test_no_input_provider_reads_or_writes_hardware(monkeypatch):
    import socket
    import subprocess
    import time

    def forbidden(*args, **kwargs):
        raise AssertionError("shadow attempted external I/O or time sampling")

    with monkeypatch.context() as guard:
        guard.setattr(socket, "create_connection", forbidden)
        guard.setattr(subprocess, "Popen", forbidden)
        guard.setattr(time, "time", forbidden)
        guard.setattr(time, "monotonic", forbidden)
        assert observe_shadow(lambda: _evidence())["result"] == "FIT"
