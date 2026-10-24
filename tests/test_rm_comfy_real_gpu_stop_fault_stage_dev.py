"""Static safety gates for the single operator-only real AMD stop-fault probe.

The probe is staged, NOT run on production. No dangerous GPU worker starts
during these tests; all checks are inert source/packaging validation.
"""
from pathlib import Path
import ast
import subprocess

ROOT=Path(__file__).resolve().parents[1]
DEV=ROOT/"deploy/comfy-ondemand-dev/fault-stop-dev-20261024"
STAGE=Path("/srv/ai-data/staging/comfy-ondemand-faults-dev-20261024")

def source(name):
    return (DEV/name).read_text()

def test_syntax_and_fixed_scope():
    for name in ("run-fault-window-dev.sh","rollback-fault-window-dev.sh"):
        check=subprocess.run(["bash","-n",str(DEV/name)],
               capture_output=True,text=True,timeout=5)
        assert check.returncode==0,check.stderr
    ast.parse(source("real_comfy_gpu_fault_harness.py"))
    assert "ai-rm-comfy-ondemand-dev.service" in source("run-fault-window-dev.sh")
    assert "ai-rm-comfy-ondemand-dev.service" in source("rollback-fault-window-dev.sh")

def test_shared_operator_lock_and_one_shot_no_prod_install():
    sh=source("run-fault-window-dev.sh")
    assert "MODE=--check" in sh
    assert "--run" in sh and "id -u" in sh
    assert "flock -n 9" in sh
    assert "/srv/ai-data/staging/comfy-ondemand-maintenance-dev-20261023/.maintenance-global.lock" in sh
    assert "test ! -e /srv/ai-data/staging/comfy-ondemand-maintenance-dev-20261023/dev-residency.blocked" in sh
    assert "WATCHDOG=ai-rm-comfy-faultrestore-20261024" in sh
    assert "--on-active=12min" in sh
    assert sh.index("ROLLBACK_WATCHDOG_ARMED") < sh.index("systemctl stop ai-gateway.service")
    assert "DEV_COMFY_UID_DIRECTORY_RW_PASS" in sh
    for forbidden in ("systemctl disable ","systemctl enable ",
                      "systemctl daemon-reload","update-grub","setpci",
                      "nvidia-smi -pl","rmmod","modprobe"):
        assert forbidden not in sh

def test_fault_is_only_expected_after_real_gpu_image():
    s=source("real_comfy_gpu_fault_harness.py")
    assert "engine.exercise()" in s
    assert "DEV_INJECTED_STOP_REFUSAL_AFTER_REAL_VAE" in s
    assert "DEV_EXPECTED_STOP_FAULT_RM_FENCED_PASS" in s
    assert "result.get(\"image\")" in s
    assert "engine.MARKER.is_file()" in s
    assert "result.get(\"recovery_marker_left\") is not True" in s
    assert 'state.get("ActiveState")!="active"' in s
    assert "triggered[0]" in s
    assert "real_comfy_gpu_rm_harness.py" in s

def test_rollback_cannot_start_prod_before_dev_service_stops():
    s=source("rollback-fault-window-dev.sh")
    assert 'timeout 40 systemctl stop "$DEV"' in s
    assert "ROLLBACK_BLOCKED_DEV_MAINPID" in s
    assert "ROLLBACK_BLOCKED_TEST_CGROUP_NONEMPTY" in s
    assert "ROLLBACK_BLOCKED_TEST_PORT_STILL_OPEN" in s
    assert s.index('systemctl stop "$DEV"') < s.index("systemctl start comfyui.service")
    assert s.index("systemctl start comfyui.service") < s.index("systemctl start ai-gateway.service")

def test_operator_must_get_expected_fault_tag_before_success():
    sh=source("run-fault-window-dev.sh")
    assert "^DEV_EXPECTED_STOP_FAULT_RM_FENCED_PASS$" in sh
    assert "DEV_EXPECTED_STOP_FAILURE_PENDING_ROLLBACK" in sh
    assert "if timeout 400" in sh
    assert "PRODUCTION_RESTORE_PASS" in sh
    assert "GPU_OWNER_FREE_WINDOW_PASS" in sh

def test_host_staging_copy_matches_repository_when_available():
    if not STAGE.exists():
        return
    for name in ("run-fault-window-dev.sh",
                 "rollback-fault-window-dev.sh",
                 "real_comfy_gpu_fault_harness.py"):
        assert (STAGE/name).read_bytes()==(DEV/name).read_bytes()
