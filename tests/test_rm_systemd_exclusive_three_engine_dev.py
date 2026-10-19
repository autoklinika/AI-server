"""Offline safeguards for the fixed operator systemd GPU transition pilot.

Only parses the shell file and invokes bash -n; no root/service/GPU actions.
"""
from pathlib import Path
import subprocess
import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "tools/run_rm_systemd_exclusive_three_engine_dev.sh"


def test_shell_is_syntactically_valid():
    result = subprocess.run(["bash", "-n", str(SCRIPT)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_exact_order_of_three_engines_and_no_auto_n1_grant():
    s = SCRIPT.read_text()
    pos = [s.index(f"BEGIN_{name}") for name in
           ("OLLAMA_VULKAN_LIGHT_MODEL", "COMFYUI_ROCM_INITIALIZATION", "VISION_FIXED_ROCM_64")]
    assert pos == sorted(pos)
    assert "N1_REAL_GPU_GRANT=NOT_ADMITTED" in s
    assert "GLOBAL_GPU_REUSE_SAFE=NOT_VERIFIED" in s
    assert "NonApprovingSafetyAdapter" not in s


def test_system_manager_enforcement_and_nonroot_role():
    s = SCRIPT.read_text()
    for value in ("sudo systemd-run --system", "DevicePolicy=strict",
                  "DeviceAllow=/dev/kfd rw", "DeviceAllow=/dev/dri/renderD128 rw",
                  "KillMode=control-group", "Restart=no", "RuntimeMaxSec=95s",
                  "User=$user", "NoNewPrivileges=yes", "sudo -v"):
        assert value in s
    assert 'if [[ "$(id -u)" -eq 0 ]]' in s
    assert "sudo systemctl stop" in s
    assert "sudo systemctl start" not in s
    assert "systemctl set-default" not in s


def test_cleanup_stays_owned_and_blocks_on_unknown_gpu():
    s = SCRIPT.read_text()
    assert "current=\"$unit\"" in s
    assert "trap cleanup EXIT" in s
    assert "BLOCKED: GPU owners" in s
    assert "STOP_FAILED: cgroup still has tasks" in s
    assert "if (( stable >= 3 )); then return 0; fi" in s
    assert "BLOCKED: postflight not verified" in s
    assert "BLOCKED: foreign GPU owner" in s
    assert "grep -q '^DevicePolicy=strict$'" in s


@pytest.mark.parametrize("forbidden", [
    "systemctl restart", "systemctl enable", "systemctl disable",
    "amdgpu reset", "rmmod", "modprobe", "SIGSTOP", "SIGCONT",
    "chmod /dev", "chown /dev", "--dangerously-bypass"
])
def test_never_changes_global_host_policy(forbidden):
    assert forbidden not in SCRIPT.read_text()
