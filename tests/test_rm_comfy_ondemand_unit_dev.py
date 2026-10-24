"""Static safety gates for the staged, UNINSTALLED on-demand ComfyUI unit."""
import os
from pathlib import Path
import subprocess
import sys

from ai_bridge.gateway.comfy_ondemand_dev import (
    OnDemandComfyLifecycle, ServiceIdentity, UnapprovedController,
    OnDemandComfyError,
)

ROOT=Path(__file__).resolve().parents[1]
UNIT=ROOT/"deploy/comfy-ondemand-dev/ai-rm-comfy-ondemand-dev.service"


def test_draft_unit_is_nonpersistent_and_short_lived():
    text=UNIT.read_text()
    for term in (
        "Type=simple", "Restart=no", "KillMode=control-group",
        "MemoryMax=12G", "MemorySwapMax=0", "TasksMax=256",
        "RuntimeMaxSec=300", "TimeoutStopSec=20", "NoNewPrivileges=yes",
        "DevicePolicy=closed", "DeviceAllow=/dev/kfd rw",
        "DeviceAllow=/dev/dri/renderD128 rw", "User=harrypotter",
        "--listen 127.0.0.1", "--port 11657",
        "RequiresMountsFor=/srv/ai-data/comfyui-output",
    ):
        assert term in text
    assert not any(line.strip()=="[Install]" for line in text.splitlines())
    assert "WantedBy=" not in text
    assert "Restart=always" not in text
    assert "--listen 0.0.0.0" not in text
    assert "ExecStartPost=" not in text
    assert "systemctl" not in text


def test_systemd_unit_is_statically_valid(tmp_path):
    # Keep the deployable unit unchanged. CI does not have the ComfyUI venv,
    # so verify a disposable copy with only the executable substituted.
    text = UNIT.read_text()
    executable = "/opt/comfyui/venv/bin/python"
    original_start = f"ExecStart={executable} "
    assert text.count(original_start) == 1, "Unexpected ComfyUI ExecStart"
    ci_unit = tmp_path / UNIT.name
    ci_unit.write_text(text.replace(original_start, f"ExecStart={sys.executable} ", 1))
    run = subprocess.run(
        ["/usr/bin/systemd-analyze", "verify", str(ci_unit)],
        capture_output=True, text=True, timeout=10, check=False,
    )
    assert run.returncode == 0, run.stderr[-1000:]

    # On the real host, verify the unmodified production-path unit as well.
    # If its venv directory exists, a missing or non-executable Python is
    # a regression and must not be silently treated as a CI-only limitation.
    runtime_python = Path(executable)
    if runtime_python.parent.is_dir():
        assert runtime_python.is_file() and os.access(runtime_python, os.X_OK), (
            f"ComfyUI host executable missing or not executable: {runtime_python}"
        )
        host_run = subprocess.run(
            ["/usr/bin/systemd-analyze", "verify", str(UNIT)],
            capture_output=True, text=True, timeout=10, check=False,
        )
        assert host_run.returncode == 0, host_run.stderr[-1000:]


def test_activation_requires_trusted_controller_and_full_token():
    import asyncio
    async def run():
        c=UnapprovedController()
        try:
            await c.start()
        except OnDemandComfyError:
            pass
        else:
            raise AssertionError("unapproved process controller must not start")
        assert c.running(ServiceIdentity("boot","inv",55,"/dev/cgroup",111)) is False
    asyncio.run(run())


def test_production_units_must_not_be_deactivated_in_dev_sources():
    source=(ROOT/"src/ai_bridge/gateway/comfy_ondemand_dev.py").read_text()
    for forbidden in (
        "systemctl stop comfyui.service",
        "systemctl disable comfyui.service",
        "systemctl --system start",
        "systemctl --system stop",
        "sudo ",
        "os.kill(",
        "subprocess.run(",
        "SIGSTOP",
        "SIGCONT",
    ):
        assert forbidden not in source
    assert "hold_until_service_stop=True" in source
    assert "finalize_after_service_stop()" in source
    assert "residency._dirty()" in source


def test_legacy_gateway_service_configuration_remains_unmodified():
    # The change lives in DEV code; no systemd install/remove scripts are
    # shipped by this feature. Gateway production dependency remains untouched.
    deploy=ROOT/"deploy/comfy-ondemand-dev"
    assert {p.name for p in deploy.iterdir()} <= {
        "README.md","ai-rm-comfy-ondemand-dev.service",
        "maintenance-20261023",  # operator-only DEV scripts, no installed units
        "fault-stop-dev-20261024",  # scoped, one-shot DEV negative test scripts
        "FULLCHAIN_SYSTEMD_RECOVERY_DEV_2026-10-24_PL.md",  # documentation only
    }
