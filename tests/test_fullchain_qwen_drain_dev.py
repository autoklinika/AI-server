"""CPU-only contract for post-Qwen unload with independent RM recovery fence."""
from __future__ import annotations

from dataclasses import replace
import importlib.util
from pathlib import Path
import sys

import pytest

SOURCE = (Path(__file__).resolve().parents[1]
          / "tools/local_image/fullchain_qwen_drain_dev.py")
spec = importlib.util.spec_from_file_location("fullchain_qwen_drain_contract", SOURCE)
assert spec and spec.loader
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)


@pytest.fixture
def fence():
    return m.DrainFence(
        worker_identity_gone=True,
        gateway_dev_port_closed=True,
        comfy_dev_port_closed=True,
        comfy_dev_unit_inactive=True,
        comfy_dev_mainpid_zero=True,
        comfy_dev_cgroup_empty=True,
        watchdog_armed=True,
        recovery_marker_present=True,
        production_comfy_inactive=True,
        production_gateway_inactive=True,
        ollama_unit_active=True,
    )


class Simulation:
    def __init__(self, resident=(m.QWEN,), owners=(11111,)):
        self.models = resident
        self.owners = owners
        self.groups = {11111: m.OLLAMA_CGROUP}
        self.t = 0.0
        self.unloads = []
        self.events = []

    def clock(self):
        return self.t

    def sleep(self, delay):
        self.t += delay

    def list_models(self):
        self.events.append("ps")
        return {"models": [{"name": name} for name in self.models]}

    def unload(self, name):
        self.events.append("unload")
        self.unloads.append(name)
        self.models = ()
        self.owners = ()

    def list_owners(self):
        self.events.append("fuser")
        return self.owners

    def cgroup(self, pid):
        return self.groups.get(pid)

    def run(self, fence, **kwargs):
        return m.drain_qwen_with_fence(
            fence=fence,
            read_models=self.list_models,
            unload_exact_qwen=self.unload,
            read_amd_pids=self.list_owners,
            process_cgroup=self.cgroup,
            monotonic=self.clock,
            sleep=self.sleep,
            **kwargs,
        )


def test_qwen_unloads_only_with_verified_owner_and_fence(fence):
    sim = Simulation()
    result = sim.run(fence)
    assert sim.unloads == [m.QWEN]
    assert result["model_unloaded"] is True
    assert result["amd_descriptors_empty"] is True
    assert result["recovery_marker_cleared"] is False
    assert result["production_started"] is False
    assert result["gpu_reuse_safe"] == "NOT_VERIFIED"


@pytest.mark.parametrize("field", list(m.DrainFence.__dataclass_fields__))
def test_missing_fence_attribute_refuses_before_unload(fence, field):
    sim = Simulation()
    with pytest.raises(m.ModelDrainBlocked, match="fenced"):
        sim.run(replace(fence, **{field: False}))
    assert sim.unloads == []


def test_already_unloaded_must_have_empty_amd_owners(fence):
    sim = Simulation(resident=(), owners=())
    result = sim.run(fence)
    assert sim.unloads == []
    assert result["model_unloaded"] is True


@pytest.mark.parametrize("resident", [
    ("qwen3.8:27b-p4-64k-gpu-wvc-v1",),
    ("clef:latest",),
    (m.QWEN, "bge-m3:latest"),
])
def test_foreign_model_never_unloaded(fence, resident):
    sim = Simulation(resident=resident)
    with pytest.raises(m.ModelDrainBlocked, match="foreign"):
        sim.run(fence)
    assert sim.unloads == []


@pytest.mark.parametrize("owner_cgroup", [
    "/system.slice/comfyui.service",
    "/user.slice/user-1000.slice",
    "/system.slice/ai-gateway.service",
    None,
])
def test_foreign_gpu_holder_never_triggers_unload(fence, owner_cgroup):
    sim = Simulation()
    sim.groups[11111] = owner_cgroup
    with pytest.raises(m.ModelDrainBlocked, match="owner"):
        sim.run(fence)
    assert sim.unloads == []


def test_unknown_gpu_owners_fails_closed(fence):
    sim = Simulation(owners=None)
    with pytest.raises(m.ModelDrainBlocked, match="owner"):
        sim.run(fence)
    assert sim.unloads == []


def test_empty_inventory_foreign_gpu_owner_blocks(fence):
    sim = Simulation(resident=(), owners=(11111,))
    with pytest.raises(m.ModelDrainBlocked, match="not empty"):
        sim.run(fence)
    assert sim.unloads == []


def test_cleanup_must_wait_for_empty_residency_and_descriptors(fence):
    sim = Simulation()
    def unload_but_leak(name):
        sim.unloads.append(name)
        sim.models = ()
        # Simulate lingering /dev/kfd after model exit.
    sim.unload = unload_but_leak
    with pytest.raises(m.ModelDrainBlocked, match="descriptors"):
        sim.run(fence)
    assert sim.unloads == [m.QWEN]


def test_inventory_malformation_does_not_call_unload(fence):
    sim = Simulation()
    sim.list_models = lambda: {"models": [{"name": 42}]}
    with pytest.raises(m.ModelDrainBlocked, match="untrusted"):
        sim.run(fence)
    assert sim.unloads == []


def test_timeout_does_not_release_fence(fence):
    sim = Simulation()
    def never_unload(name):
        sim.unloads.append(name)
        # Simulate returned HTTP 200 but reloading status never clears.
    sim.unload = never_unload
    with pytest.raises(m.ModelDrainBlocked, match="deadline"):
        sim.run(fence, deadline_seconds=1, poll_seconds=.1)
    assert sim.unloads == [m.QWEN]


@pytest.mark.parametrize("seconds,poll", [(.01,.25),(121,.25),(4,0),(4,3)])
def test_invalid_time_budget_fails_without_unload(fence, seconds, poll):
    sim = Simulation()
    with pytest.raises(m.ModelDrainBlocked, match="timeout"):
        sim.run(fence, deadline_seconds=seconds, poll_seconds=poll)
    assert sim.unloads == []
