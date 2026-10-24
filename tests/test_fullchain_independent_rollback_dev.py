"""One-shot rollback ordering and fail-closed behavior, CPU-only."""
from __future__ import annotations

from dataclasses import replace
import importlib.util
from pathlib import Path
import sys

import pytest

SOURCE = Path(__file__).resolve().parents[1] / "tools/local_image/fullchain_independent_rollback_dev.py"
spec = importlib.util.spec_from_file_location("fullchain_rollback_state_machine", SOURCE)
assert spec and spec.loader
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)

def healthy():
    return m.DriverEvidence(**{x:True for x in m.DriverEvidence.__dataclass_fields__})

class FakeBackend:
    def __init__(self, fail=None, *, driver=None):
        self.fail=fail
        self.events=[]
        self.restored=[]
        self.watchdog_active=True
        self.marker=True
        self.driver=driver if driver is not None else healthy()
        self.authorized=True
        self.backup=True

    def fail_at(self, name):
        self.events.append(name)
        if name == self.fail:
            raise RuntimeError("injected failure at " + name)

    def root_authority_verified(self):return self.authorized
    def watchdog_armed(self):return self.watchdog_active
    def evidence_backup_exists(self):return self.backup
    def snapshot(self,label):self.fail_at("snapshot:"+label)
    def stop_captured_worker(self):self.fail_at("stop_worker")
    def stop_dev_gateway(self):self.fail_at("stop_gateway")
    def stop_fixed_comfy_unit(self):self.fail_at("stop_dev_comfy")
    def confirm_only_approved_processes_stopped(self):self.fail_at("verify_closed")
    def drain_exact_qwen(self):self.fail_at("qwen_drain")
    def check_no_amd_owners(self):self.fail_at("amd_empty")
    def driver_evidence(self):
        self.fail_at("driver_evidence")
        return self.driver
    def restore_unit(self,unit):
        self.fail_at("restore:"+unit)
        self.restored.append(unit)
    def check_production_smoke(self):self.fail_at("smoke")
    def archive_evidence(self):self.fail_at("archive")
    def disarm_watchdog(self):
        self.fail_at("disarm")
        self.watchdog_active=False
    def log(self,event):self.events.append(event)

def test_approved_simulated_one_shot_restore_sequence():
    backend=FakeBackend()
    result=m.recovery_once(backend)
    assert result["verdict"]=="SIMULATED_ROLLBACK_PASS"
    assert result["gpu_reuse_safe"]=="NOT_VERIFIED_BY_THIS_ORCHESTRATOR"
    assert backend.restored==["comfyui.service","ai-gateway.service"]
    assert backend.events.index("archive") < backend.events.index("restore:comfyui.service")
    assert backend.events.index("amd_empty") < backend.events.index("restore:comfyui.service")
    assert backend.watchdog_active is False
    assert backend.marker is True   # no implicit deletion; evidence archived separately

@pytest.mark.parametrize("precondition",["authorized","backup","watchdog_active"])
def test_missing_root_watchdog_or_backup_never_stops_anything(precondition):
    b=FakeBackend()
    setattr(b,precondition,False)
    result=m.recovery_once(b)
    assert result["verdict"]=="BLOCKED"
    assert b.restored==[] and b.events==["BLOCKED:RollbackBlocked"]
    assert b.marker and (not b.watchdog_active if precondition=="watchdog_active" else b.watchdog_active)

@pytest.mark.parametrize("failure",[
    "snapshot:pre-recovery","stop_worker","stop_gateway","stop_dev_comfy",
    "verify_closed","qwen_drain","amd_empty","driver_evidence","archive",
])
def test_failed_recovery_before_restore_must_not_start_production(failure):
    b=FakeBackend(fail=failure)
    result=m.recovery_once(b)
    assert result["verdict"]=="BLOCKED"
    assert result["production_restore"]=="NOT_STARTED"
    assert b.restored==[]
    assert b.marker and b.watchdog_active

@pytest.mark.parametrize("field",list(m.DriverEvidence.__dataclass_fields__))
def test_missing_driver_observation_blocks_hardware_reuse(field):
    b=FakeBackend(driver=replace(healthy(), **{field: False}))
    result=m.recovery_once(b)
    assert result["verdict"]=="BLOCKED"
    assert result["failure_class"]=="RollbackBlocked"
    assert "START_ORIGINAL_COMFY" not in result["steps"]
    assert b.restored==[]
    assert b.watchdog_active

@pytest.mark.parametrize("failure",[
    "restore:comfyui.service", "restore:ai-gateway.service",
    "smoke","snapshot:post-recovery","disarm",
])
def test_partial_restore_keeps_watchdog_and_no_pass(failure):
    b=FakeBackend(fail=failure)
    result=m.recovery_once(b)
    assert result["verdict"]=="BLOCKED"
    assert result["production_restore"]=="PARTIAL_OR_UNVERIFIED"
    assert b.watchdog_active and b.marker

def test_watchdog_command_is_fixed_to_root_owned_copy():
    cmd=m.watchdog_plan()
    assert cmd[0]=="/usr/bin/systemd-run"
    assert "--system" in cmd and "--on-active=12min" in cmd
    assert "--unit=ai-rm-fullchain-rollback-20261024" in cmd
    assert cmd[-3:]==("/usr/bin/python3",str(m.ROOT_OWNED_COPY),"--execute")
    assert not any("sudo" in v or "shell" in v or "--user" in v for v in cmd)

def test_cli_not_executable_from_worktree():
    source=SOURCE.read_text()
    assert 'sys.argv[1:] != ["--check"]' in source
    assert "runner_installed" in source
    assert "WATCHDOG_UNIT" in source
