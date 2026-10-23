"""Offline preflight for a fixed, operator-only one-shot GPU maintenance pilot."""
from pathlib import Path
import ast
import re
import subprocess

ROOT=Path(__file__).resolve().parents[1]
DIR=ROOT/"deploy/comfy-ondemand-dev/maintenance-20261023"

def scripts():
    return ((DIR/"run-maintenance-dev.sh").read_text(),
            (DIR/"rollback.sh").read_text(),
            (DIR/"real_comfy_gpu_rm_harness.py").read_text())

def test_bash_and_python_source_syntax():
    for name in ("run-maintenance-dev.sh","rollback.sh"):
        p=subprocess.run(["bash","-n",str(DIR/name)],capture_output=True,text=True,timeout=4)
        assert p.returncode==0,p.stderr
    ast.parse((DIR/"real_comfy_gpu_rm_harness.py").read_text())

def test_preflight_refuses_nonroot_and_shared_resource():
    script,_,_=scripts()
    assert "MODE=--check" in script
    assert 'if [[ "$MODE" == "--check" ]]' in script
    assert 'if [[ "$(id -u)" -ne 0 ]]' in script
    assert script.index('if [[ "$(id -u)" -ne 0 ]]') < script.index('systemctl stop ai-gateway.service')
    for token in (
        'flock -n 9', 'dev-residency.blocked',
        'real-comfy-gpu-result.json', 'MAINTENANCE_PREFLIGHT_PASS',
        'gateway_gpu', 'comfyui.service', 'ai-gateway.service',
        'ollama.service', 'gpu[0]', 'owners_rc',
    ):
        if token=='gateway_gpu':
            continue
        assert token in script
    assert 'MODE=--check' in script
    assert 'systemd-run --system --on-active=12min' in script

def test_rollback_armed_before_any_production_stop():
    script,rollback,_=scripts()
    assert script.index("ROLLBACK_WATCHDOG_ARMED") < script.index("systemctl stop ai-gateway.service")
    assert script.index('needs_rollback=1') < script.index('systemctl stop ai-gateway.service')
    assert 'trap cleanup EXIT' in script
    assert 'trap ' in script
    assert '/run/ai-rm-comfy-dev-safety-20261023/rollback.sh' in script
    assert 'install -o root -g root -m 0700' in script
    assert 'if timeout 400' in script
    assert 'timeout --signal=TERM --kill-after=15s 240s' in script
    assert 'DEV=ai-rm-comfy-ondemand-dev.service' in rollback
    assert rollback.index('systemctl stop "$DEV"') < rollback.index('systemctl start comfyui.service')
    assert rollback.index('systemctl start comfyui.service') < rollback.index('systemctl start ai-gateway.service')
    assert 'ROLLBACK_BLOCKED_TEST_CGROUP_NONEMPTY' in rollback
    assert 'ROLLBACK_BLOCKED_TEST_PORT_STILL_OPEN' in rollback
    assert 'ROLLBACK_PRODUCTION_HTTP_SMOKE_PASS' in rollback

def test_fixed_amd_device_cgroup_and_one_rm_scheduler():
    _,_,python=scripts()
    for required in (
        "ai-rm-comfy-ondemand-dev.service",
        "DevicePolicy=closed",
        "DeviceAllow=/dev/kfd rw",
        "DeviceAllow=/dev/dri/renderD128 rw",
        "MemoryMax=9G",
        "RuntimeMaxSec=240s",
        "--uid=harrypotter",
        "real-comfy-gpu-result.json",
        "gateway_comfy_ondemand_dev_mode=True",
        "gateway_max_concurrency=1",
        "ServiceIdentity",
        "process_start_ticks",
        "rec.external_use_id",
    ):
        if required=="rec.external_use_id":
            continue
        assert required in python
    assert 'residency.resume_comfy=None' in python
    assert '--cpu' in python  # explicitly refused in process identity.
    assert 'b"--cpu" not in cmd' in python
    assert '--disable-all-custom-nodes' not in python
    assert 'CUDA_VISIBLE_DEVICES=-1' not in python
    assert 'ROCR_VISIBLE_DEVICES=-1' not in python
    assert 'HIP_VISIBLE_DEVICES=-1' not in python
    assert 'GPU_REUSE_SAFE=PASS' not in python

def test_no_persistent_or_driver_changes():
    sh,roll,py=scripts()
    for fragment in (
        "systemctl disable", "systemctl mask", "systemctl enable",
        "systemctl daemon-reload", "update-grub", "setpci",
        "nvidia-smi -pl", "rmmod", "modprobe",
        "systemctl set-default", "systemctl isolate",
    ):
        assert fragment not in sh+roll+py
    # Neither primary script nor rollback change boot dependencies.
    assert "rm -rf /etc/systemd" not in sh+roll+py

def test_watchdog_encloses_bounded_pilot_and_restore():
    script,_,_=scripts()
    timer=re.search(r"--on-active=(\d+)min",script)
    pilot=re.search(r"kill-after=15s (\d+)s",script)
    restore=re.search(r"if timeout (\d+) /usr/bin/bash",script)
    assert timer and pilot and restore
    assert int(timer.group(1))*60 > int(pilot.group(1))+int(restore.group(1))

def test_host_sources_match_archive_when_available():
    stage=Path("/srv/ai-data/staging/comfy-ondemand-maintenance-dev-20261023")
    if not stage.exists():
        return
    for name in ("run-maintenance-dev.sh","rollback.sh","real_comfy_gpu_rm_harness.py"):
        assert (stage/name).read_bytes()==(DIR/name).read_bytes()
