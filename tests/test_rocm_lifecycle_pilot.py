"""CPU-only regression for narrow single-owner ROCm lifecycle evidence."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from ai_bridge.gateway import rocm_lifecycle_pilot as mod
from ai_bridge.gateway.rocm_maintenance_pilot import PilotBlocked


def test_live_owner_matches_only_original_worker(tmp_path):
    (tmp_path / "211").mkdir()
    assert mod.inspect_live_holder(211, kfd_root=tmp_path, fuser="211")["status"] == "WORKER_OWNER_OBSERVED"
    assert mod.inspect_live_holder(211, kfd_root=tmp_path, fuser="")["worker_pid"] == 211


@pytest.mark.parametrize("kfd,owners", [([], ""), (["13"], "211"),
                                          (["211"], "13"), (["13"], "")])
def test_unknown_or_foreign_owners_block(tmp_path, kfd, owners):
    for pid in kfd:
        (tmp_path / pid).mkdir()
    with pytest.raises(PilotBlocked):
        mod.inspect_live_holder(211, kfd_root=tmp_path, fuser=owners)


class FakeRuntime:
    def __init__(self, folder):
        self.events = []
    def activate(self, child):
        self.events.append("activated")
    def read_result(self, child):
        self.events.append("computed")
        return {"status": "WORKER_LOCAL_SYNC"}
    def finish(self, child):
        self.events.append("released")
    def abort(self, child):
        self.events.append("aborted")


class FakeObserver:
    def __init__(self, marker, runtime, marker_label):
        assert marker_label == "HARDWARE-PILOT"
        self.marker = marker
        self.runtime = runtime
        self._child = SimpleNamespace(pid=211)
        self.identity = SimpleNamespace(pid=211, boot_id="boot-test")
        self.cancelled = False
    def start(self):
        self.marker.write_text("HARDWARE-PILOT: attempt reserved")
        return self.identity
    def observe(self, *, timeout):
        assert timeout > 0
        return "PROCESS_CLOSED"
    def cancel(self):
        self.cancelled = True


def test_complete_lifecycle_never_certifies_gpu_reuse(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "WorkerObserver", FakeObserver)
    folder = tmp_path / "attempt"
    report = mod.run_once(folder, preflight=lambda: {"idle": True},
                          runtime_factory=FakeRuntime,
                          live_inspector=lambda pid: {"worker_pid": pid, "status": "WORKER_OWNER_OBSERVED"})
    assert report["outcome"] == "WORKER_LOCAL_SYNC_AND_CLOSED"
    assert report["gpu_reuse_safe"] == "NOT_VERIFIED"
    assert report["pid"] == 211
    assert report["postflight"]["idle"] is True
    assert (folder / "ownership.dirty").exists()
    assert json.loads((folder / "result.json").read_text()) == report
    with pytest.raises(PilotBlocked, match="exists"):
        mod.run_once(folder, preflight=lambda: {})


def test_missing_live_owner_fails_closed(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "WorkerObserver", FakeObserver)
    folder = tmp_path / "denied"
    with pytest.raises(PilotBlocked):
        mod.run_once(folder, preflight=lambda: {"idle": True},
                     runtime_factory=FakeRuntime,
                     live_inspector=lambda pid: (_ for _ in ()).throw(PilotBlocked("owner absent")))
    report = json.loads((folder / "result.json").read_text())
    assert report["outcome"] == "DIRTY"
    assert report["gpu_reuse_safe"] == "NOT_VERIFIED"
    assert (folder / "ownership.dirty").exists()


def test_no_gpu_after_service_failed_preflight(tmp_path):
    def blocked():
        raise PilotBlocked("services active")
    with pytest.raises(PilotBlocked):
        mod.run_once(tmp_path / "no-run", preflight=blocked)
    assert not (tmp_path / "no-run").exists()
