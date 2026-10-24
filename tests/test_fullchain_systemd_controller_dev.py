"""Static fixed-service systemd controller contract. NEVER starts a unit."""
from __future__ import annotations

from dataclasses import replace
import importlib.util
from pathlib import Path
import sys

import pytest

SOURCE = Path(__file__).resolve().parents[1] / "tools/local_image/fullchain_systemd_controller_dev.py"
spec = importlib.util.spec_from_file_location("fullchain_fixed_systemd_contract", SOURCE)
assert spec and spec.loader
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)
GIB = 1024**3

@pytest.fixture()
def fence():
    return m.StartFence(**{name: True for name in m.StartFence.__dataclass_fields__})

@pytest.fixture()
def limits():
    return m.Limits(
        memory_high_bytes=14 * GIB, memory_max_bytes=16 * GIB,
        available_host_bytes=25 * GIB, model_weights_bytes=12 * GIB,
    )

@pytest.fixture()
def identity():
    return m.ServiceIdentity(
        boot_id="bc4d4bf3-1ebd-4f2e-b327-65e1594c5c51",
        invocation_id="f"*32, pid=71712, start_ticks=424242, cgroup=m.CGROUP,
    )

def test_exact_transient_cmd_has_one_fixed_unit_and_single_gpu(fence,limits):
    plan = m.launch_plan(fence, limits)
    assert plan[0] == "/usr/bin/systemd-run"
    assert "--system" in plan and "--collect" in plan
    assert "--unit=ai-rm-comfy-ondemand-dev.service" in plan
    assert "--property=DevicePolicy=closed" in plan
    assert "--property=DeviceAllow=/dev/kfd rw" in plan
    assert "--property=DeviceAllow=/dev/dri/renderD128 rw" in plan
    assert not any("/dev/nvidia" in v or "Restart=always" in v for v in plan)
    assert "--property=Restart=no" in plan
    assert "--property=KillMode=control-group" in plan
    assert "--property=MemorySwapMax=0" in plan
    assert "--property=MemoryMax="+str(16 * GIB) in plan
    assert str(m.MAIN) in plan and str(m.PYTHON) in plan
    assert "--cpu" not in plan and "--enable-manager" not in plan
    assert plan[-len(m._fixed_flags()):] == m._fixed_flags()
    assert not any(v in ("sh", "bash", "-c") for v in plan)

@pytest.mark.parametrize("field",list(m.StartFence.__dataclass_fields__))
def test_start_requires_every_independently_verified_fence(fence,limits,field):
    with pytest.raises(m.ControllerBlocked, match="fenced"):
        m.launch_plan(replace(fence, **{field: False}), limits)

@pytest.mark.parametrize("max_gib,high_gib,avail_gib,weights_gib",[
    (12,10,25,12),(16,17,25,12),(19,16,25,12),
    (16,14,19,12),(16,14,25,15),
])
def test_insufficient_or_overcommitted_mem_rejects_start(
    fence,max_gib,high_gib,avail_gib,weights_gib
):
    with pytest.raises(m.ControllerBlocked):
        m.launch_plan(fence, m.Limits(
            high_gib*GIB,max_gib*GIB,avail_gib*GIB,weights_gib*GIB))

def test_stop_plan_refuses_mismatched_identity(identity):
    assert m.stop_plan(identity) == (
        "/usr/bin/systemctl", "--system", "stop", "ai-rm-comfy-ondemand-dev.service",
    )
    for change in ({"cgroup":"/system.slice/comfyui.service"},
                   {"pid":0},{"invocation_id":"INVALID"}, {"start_ticks":0}):
        with pytest.raises(m.ControllerBlocked):
            m.stop_plan(replace(identity, **change))

def test_duplicate_systemd_show_is_untrusted():
    with pytest.raises(m.ControllerBlocked,match="duplicate"):
        m.parse_show("MainPID=7\nMainPID=8")

def _stat(identity):
    vals=["S"]*25
    vals[19]=str(identity.start_ticks)
    return str(identity.pid)+" (ComfyUI python) "+" ".join(vals)

def _show(identity):
    return "\n".join([
        "LoadState=loaded", "ActiveState=active", "MainPID="+str(identity.pid),
        "InvocationID="+identity.invocation_id, "ControlGroup="+m.CGROUP,
        "User=harrypotter", "DevicePolicy=closed", "Restart=no",
        "KillMode=control-group",
    ])

def _verify(identity,**changes):
    props=dict(show=_show(identity),proc_stat=_stat(identity),
               proc_cgroup="0::"+m.CGROUP+"\n",
               proc_cmdline=b"\x00".join([
                   b"/opt/comfyui/venv/bin/python",
                   b"/opt/comfyui/ComfyUI/main.py",
                   *(flag.encode() for flag in m._fixed_flags()),
                   b"",
               ]),boot_id=identity.boot_id,
               amd_owners=(identity.pid,), owner_cgroup=lambda _ : m.CGROUP)
    props.update(changes)
    return m.verify_running(identity,**props)

def test_full_pinned_live_identity(identity):
    assert _verify(identity)

@pytest.mark.parametrize("changes",[
    {"show":"LoadState=loaded\nActiveState=active\nMainPID=100"},
    {"proc_stat":"14 (fake) S"},
    {"proc_cgroup":"0::/user.slice/user-1000.slice"},
    {"proc_cmdline":b"python\x00ComfyUI/main.py\x00--cpu\x00"},
    {"boot_id":"00000000-0000-0000-0000-000000000000"},
    {"amd_owners":None},
    {"amd_owners":()},
    {"amd_owners":(71712,99999),
     "owner_cgroup":lambda pid: m.CGROUP if pid == 71712
                     else "/system.slice/ollama.service"},
    {"owner_cgroup":lambda _: "/system.slice/ollama.service"},
])
def test_foreign_process_or_unknown_owner_rejected(identity,changes):
    assert not _verify(identity,**changes)

def test_candidate_cli_never_installs_or_starts(tmp_path):
    source=SOURCE.read_text()
    assert "systemd-run" in source and "systemctl" in source
    assert "subprocess.run(" not in source
    assert 'sys.argv[1:] != ["--check"]' in source
    assert '"start_enabled": False' in source
