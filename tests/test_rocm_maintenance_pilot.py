"""No GPU is touched in these tests; the real payload remains hardcoded."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from ai_bridge.gateway import rocm_maintenance_pilot as pilot
from ai_bridge.gateway.rocm_test_worker import EXPECTED_PCI, WORKLOAD


def pci_root(tmp_path):
    root = tmp_path / "pci"
    dev = root / EXPECTED_PCI
    dev.mkdir(parents=True)
    (dev / "vendor").write_text("0x1002")
    (dev / "device").write_text("0x150e")
    return root


def test_gate_pass_requires_all_services_inactive_and_identity(tmp_path):
    assert pilot.check_readiness(query=lambda _: "inactive", kfd=[],
        gpu_users="", device_root=pci_root(tmp_path))["reuse_safe"] == "NOT_VERIFIED"


@pytest.mark.parametrize("reason", ["active", "kfd", "gpu_users", "wrong_pci", "unknown"])
def test_gate_blocks_unsafe_states(tmp_path, reason):
    root = pci_root(tmp_path)
    if reason == "wrong_pci":
        (root / EXPECTED_PCI / "vendor").write_text("0x8086")
    with pytest.raises(pilot.PilotBlocked):
        pilot.check_readiness(
            query=lambda _: ("active" if reason == "active" else
                             "unknown" if reason == "unknown" else "inactive"),
            kfd=["123"] if reason == "kfd" else [],
            gpu_users="123" if reason == "gpu_users" else "",
            device_root=root)


class FakeObserver:
    payload = None
    fail = False
    def __init__(self, marker, runtime=None, marker_label=None):
        assert marker_label == "HARDWARE-PILOT"
        self.marker = marker
        self.folder = marker.parent
    def start(self):
        self.marker.write_text("DIRTY")
        return SimpleNamespace(pid=123, boot_id="test-boot")
    def observe(self, *, timeout):
        if self.fail:
            raise TimeoutError("injected")
        (self.folder / "worker.stdout").write_text(json.dumps(self.payload))
        return "PROCESS_CLOSED"


def test_fixed_worker_success_does_not_authorize_reuse(tmp_path, monkeypatch):
    FakeObserver.fail = False
    FakeObserver.payload = {"schema": 1, "workload": WORKLOAD, "pci_bdf": EXPECTED_PCI,
                            "local_synced": True, "status": "WORKER_LOCAL_SYNC"}
    monkeypatch.setattr(pilot, "WorkerObserver", FakeObserver)
    folder = tmp_path / "hardware-01"
    result = pilot.run_once(folder, preflight=lambda: {"offline": True})
    assert result["result"] == "PROCESS_CLOSED"
    assert result["gpu_reuse_safe"] == "NOT_VERIFIED"
    assert result["worker_status"] == "WORKER_LOCAL_SYNC"
    assert (folder / "ownership.dirty").exists()
    assert json.loads((folder / "result.json").read_text()) == result
    with pytest.raises(pilot.PilotBlocked, match="already exists"):
        pilot.run_once(folder, preflight=lambda: {"offline": True})


@pytest.mark.parametrize("failure", ["bad_result", "timeout", "preflight_race", "postflight_race"])
def test_failure_retains_dirty_and_denies_reuse(tmp_path, monkeypatch, failure):
    FakeObserver.fail = failure == "timeout"
    FakeObserver.payload = {"status": "fake"}
    monkeypatch.setattr(pilot, "WorkerObserver", FakeObserver)
    attempts = []
    def gate():
        attempts.append(1)
        if (failure == "preflight_race" and len(attempts) == 2 or
                failure == "postflight_race" and len(attempts) == 3):
            raise pilot.PilotBlocked("service restarted")
        return {"offline": True}
    folder = tmp_path / failure
    with pytest.raises((pilot.PilotBlocked, TimeoutError)):
        pilot.run_once(folder, preflight=gate)
    assert (folder / "ownership.dirty").exists() or failure == "preflight_race"
    report = json.loads((folder / "result.json").read_text())
    assert report["result"] == "DIRTY"
    assert report["gpu_reuse_safe"] == "NOT_VERIFIED"
    with pytest.raises(pilot.PilotBlocked):
        pilot.run_once(folder, preflight=gate)
