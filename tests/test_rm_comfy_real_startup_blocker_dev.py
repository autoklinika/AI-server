"""Negative real ComfyUI startup evidence must not be promoted to GPU PASS."""
import json
from pathlib import Path

import pytest

ROOT=Path(__file__).resolve().parents[1]
EVIDENCE=ROOT/"docs/reports/RM_COMFY_REAL_START_DEV_BLOCKED_2026-10-23.json"
PROFILE=ROOT/"deploy/comfy-ondemand-dev/ai-rm-comfy-ondemand-dev.service"
REPORT=ROOT/"docs/reports/RM_COMFY_REAL_STARTUP_DEV_BLOCKER_2026-10-23_PL.md"


def test_real_comfy_starts_are_not_a_positive_gpu_acceptance():
    e=json.loads(EVIDENCE.read_text())
    assert e["overall_result"]=="BLOCKED_REAL_COMFYUI_DEV_GPU_ACCEPTANCE"
    assert e["gpu_driver_reuse_safe"]=="NOT_VERIFIED"
    assert e["global_os_gpu_exclusivity"]=="NOT_VERIFIED"
    assert e["dev_recovery_marker_retained"] is True
    assert e["dev_process_running"] is False
    assert e["dev_port_open"] is False
    assert len(e["attempts"])==3
    assert all(x["result"]=="INCOMPLETE_FAIL_CLOSED" for x in e["attempts"])
    assert all(x["dev_rm_lease_use_admitted"] is False for x in e["attempts"])
    assert all(x["production_service_modified"] is False for x in e["attempts"])
    assert e["production_comfyui_mainpid"]>1


@pytest.mark.parametrize("name",("ROCR_VISIBLE_DEVICES=-1","CUDA_VISIBLE_DEVICES=-1"))
def test_invalid_ordinal_is_documented_and_absent_from_dev_amd_profile(name):
    text=REPORT.read_text()
    assert name in text
    # Never copy invalid negative GPU ordinal into a fixed ROCm systemd unit.
    assert name not in PROFILE.read_text()


def test_dev_cpu_mode_not_counted_as_gpu_isolation():
    e=json.loads(EVIDENCE.read_text())
    assert "--cpu" in e["scope"].lower()
    assert e["rtx_postflight"]["pcie"]=="Gen3x4"
    assert e["rtx_postflight"]["state"]=="P8"
    assert e["production_rm_state"]=="IDLE"
    assert e["production_rm_recovery_required"] is False


def test_no_positive_grants_in_report():
    s=REPORT.read_text()
    assert "NO-GO" in s
    assert "Bez kolejnych prób" in s
    assert "Brak zmian produkcyjnych" in s
