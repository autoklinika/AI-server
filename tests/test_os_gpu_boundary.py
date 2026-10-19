"""Fail-closed OS boundary tests; no device operation in unit tests."""
import json
from pathlib import Path

import pytest
from ai_bridge.gateway import os_gpu_boundary as gate


def good_units(name):
    return {"LoadState": "loaded", "ActiveState": "inactive",
            "MainPID": "0", "DevicePolicy": "strict",
            "PrivateDevices": "yes", "User": "ai-vision"}


def make_pci(tmp_path):
    pci = tmp_path / gate.EXPECTED_PCI
    pci.mkdir(parents=True)
    (pci / "vendor").write_text("0x1002")
    (pci / "device").write_text("0x150e")
    return tmp_path


def test_unmanaged_open_blocks_even_all_services_stopped(tmp_path):
    out = gate.inspect(access=lambda _: "OPEN_SUCCEEDED", unit=good_units,
                       uid=lambda: 1000, groups=lambda: [990],
                       pci_root=make_pci(tmp_path))
    assert out.decision == "BLOCKED"
    assert out.os_device_access == "UNVERIFIED_OPEN_BYPASS"
    assert out.checks["maintenance_services_stopped"] is True
    assert out.checks["unmanaged_process_can_open_gpu"] is True
    assert out.driver_reuse == "NOT_VERIFIED"
    with pytest.raises(TypeError):
        bool(out)


def test_unprivileged_denial_is_not_global_proof(tmp_path):
    out = gate.inspect(access=lambda _: "DENIED_ERRNO_13", unit=good_units,
                       pci_root=make_pci(tmp_path))
    assert out.decision == "BLOCKED"
    assert out.os_device_access == "UNVERIFIED"
    assert out.driver_reuse == "NOT_VERIFIED"


@pytest.mark.parametrize("state", ["active", "failed", "activating", "unknown"])
def test_service_active_or_unknown_not_admitted(tmp_path, state):
    def unit(name):
        data = good_units(name)
        if name == "ollama.service":
            data["ActiveState"] = state
            data["MainPID"] = "995"
        return data
    out = gate.inspect(access=lambda _: "DENIED_ERRNO_13", unit=unit,
                       pci_root=make_pci(tmp_path))
    assert not out.checks["maintenance_services_stopped"]
    assert out.decision == "BLOCKED"


@pytest.mark.parametrize("mode", ["missing-pci", "unknown-unit", "access-exception"])
def test_unknown_state_fails_closed(tmp_path, mode):
    root = make_pci(tmp_path)
    if mode == "missing-pci":
        (root / gate.EXPECTED_PCI / "vendor").unlink()
    def unit(name):
        if mode == "unknown-unit":
            raise PermissionError("not allowed")
        return good_units(name)
    def access(path):
        if mode == "access-exception":
            raise OSError("no access")
        return "DENIED_ERRNO_13"
    out = gate.inspect(access=access, unit=unit, pci_root=root)
    assert out.decision == "BLOCKED"
    assert out.driver_reuse == "NOT_VERIFIED"
    assert json.loads(json.dumps(out.as_dict()))["decision"] == "BLOCKED"


def test_no_authorization_method():
    assert not hasattr(gate.Boundary, "approve")
    assert not hasattr(gate.Boundary, "grant")
    assert gate.main.__name__ == "main"


def test_timer_properties_can_be_inspected_without_mainpid():
    from types import SimpleNamespace
    def command(*args):
        assert "LoadState,ActiveState" in args[-1]
        return SimpleNamespace(returncode=0, stdout="LoadState=loaded\nActiveState=inactive\n")
    assert gate._unit("ai-bridge-analysis.timer", command=command) == {
        "LoadState": "loaded", "ActiveState": "inactive"}
