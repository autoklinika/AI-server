#!/usr/bin/env python3
"""Candidate fixed systemd --system ComfyUI controller, DEV read-only.

Do not install, start, stop, or alter systemd with this file. The candidate
command is for a separately approved root-owned operator runner only.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import stat
import sys
from typing import Callable

BASE = Path("/srv/ai-data/staging/comfy-fullchain-dev-20261024-guarded")
UNIT = "ai-rm-comfy-ondemand-dev.service"
CGROUP = "/system.slice/" + UNIT
PYTHON = Path("/opt/comfyui/venv/bin/python")
MAIN = Path("/opt/comfyui/ComfyUI/main.py")
WORKDIR = Path("/opt/comfyui/ComfyUI")
MODELS = Path("/opt/comfyui/data/models")
PORT = 11657
RUN_SEC = 480
MIN_HEADROOM_BYTES = 2 * 1024**3
HOST_RESERVE_BYTES = 8 * 1024**3

class ControllerBlocked(RuntimeError):
    pass

@dataclass(frozen=True)
class Limits:
    memory_high_bytes: int
    memory_max_bytes: int
    available_host_bytes: int
    model_weights_bytes: int

@dataclass(frozen=True)
class StartFence:
    """Read by trusted root runner; never inferred from RM IDLE alone."""
    recovery_marker_durable: bool
    rm_exclusive_ticket_active: bool
    production_gateway_inactive: bool
    production_comfy_inactive: bool
    legacy_port_closed: bool
    dev_port_closed: bool
    rollback_watchdog_armed: bool
    amd_device_owner_free: bool
    no_prior_dev_unit: bool
    private_staging_verified: bool

@dataclass(frozen=True)
class ServiceIdentity:
    boot_id: str
    invocation_id: str
    pid: int
    start_ticks: int
    cgroup: str

def require_start_fence(fence: StartFence) -> None:
    if type(fence) is not StartFence:
        raise ControllerBlocked("missing trusted operator start fence")
    for name, value in vars(fence).items():
        if value is not True or type(value) is not bool:
            raise ControllerBlocked("fullchain start is not fenced: " + name)

def validate_limits(lim: Limits) -> None:
    if type(lim) is not Limits:
        raise ControllerBlocked("untrusted resource limits")
    if any(type(v) is not int or v <= 0 for v in vars(lim).values()):
        raise ControllerBlocked("invalid limits")
    if not (lim.memory_high_bytes <= lim.memory_max_bytes <= lim.available_host_bytes - HOST_RESERVE_BYTES):
        raise ControllerBlocked("MemoryHigh/Max exceeds safe physical host screening budget")
    if lim.memory_max_bytes < lim.model_weights_bytes + MIN_HEADROOM_BYTES:
        raise ControllerBlocked("ComfyUI memory limit insufficient for model weights plus screen margin")

def _fixed_flags() -> tuple[str, ...]:
    return (
        "--listen", "127.0.0.1", "--port", str(PORT),
        "--disable-auto-launch", "--preview-method", "none",
        "--models-directory", str(MODELS),
        "--input-directory", str(BASE / "input"),
        "--output-directory", str(BASE / "output"),
        "--temp-directory", str(BASE / "temp"),
        "--user-directory", str(BASE / "user"),
    )

def launch_plan(fence: StartFence, lim: Limits) -> tuple[str, ...]:
    """Exact argv for future authorized operator. No shell, no user unit name."""
    require_start_fence(fence)
    validate_limits(lim)
    return (
        "/usr/bin/systemd-run", "--system", "--collect", "--service-type=exec",
        "--unit=" + UNIT, "--uid=harrypotter",
        "--working-directory=" + str(WORKDIR),
        "--property=Restart=no",
        "--property=DevicePolicy=closed",
        "--property=DeviceAllow=/dev/kfd rw",
        "--property=DeviceAllow=/dev/dri/renderD128 rw",
        "--property=PrivateDevices=no",
        "--property=NoNewPrivileges=yes",
        "--property=KillMode=control-group",
        "--property=RuntimeMaxSec=" + str(RUN_SEC),
        "--property=TimeoutStopSec=20s",
        "--property=MemoryAccounting=yes",
        "--property=MemoryHigh=" + str(lim.memory_high_bytes),
        "--property=MemoryMax=" + str(lim.memory_max_bytes),
        "--property=MemorySwapMax=0",
        "--property=TasksMax=192",
        "--property=UMask=0077",
        str(PYTHON), str(MAIN), *_fixed_flags(),
    )

def stop_plan(identity: ServiceIdentity) -> tuple[str, ...]:
    if type(identity) is not ServiceIdentity or identity.cgroup != CGROUP:
        raise ControllerBlocked("refuse stop of unknown process or cgroup")
    if (type(identity.pid) is not int or identity.pid <= 1 or
        type(identity.start_ticks) is not int or identity.start_ticks <= 0 or
        not re.fullmatch(r"[0-9a-f]{32}", identity.invocation_id) or
        not re.fullmatch(r"[0-9a-f-]{36}", identity.boot_id)):
        raise ControllerBlocked("refuse stop without pinned complete identity")
    return ("/usr/bin/systemctl", "--system", "stop", UNIT)

def parse_show(text: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in text.splitlines():
        if "=" not in line:
            raise ControllerBlocked("malformed systemd show")
        key, value = line.split("=", 1)
        if key in result:
            raise ControllerBlocked("duplicate systemd property")
        result[key] = value
    return result

def proc_start_ticks(stat_text: str) -> int:
    # /proc/PID/stat second field may contain spaces and ')' in command.
    if ")" not in stat_text:
        raise ControllerBlocked("invalid /proc stat")
    try:
        ticks = int(stat_text.rsplit(")", 1)[1].split()[19])
    except (IndexError, ValueError) as exc:
        raise ControllerBlocked("invalid process birthtime") from exc
    if ticks <= 0:
        raise ControllerBlocked("invalid process birthtime")
    return ticks

def verify_running(
    identity: ServiceIdentity,
    *,
    show: str, proc_stat: str, proc_cgroup: str, proc_cmdline: bytes,
    boot_id: str, amd_owners: tuple[int, ...] | None,
    owner_cgroup: Callable[[int], str | None],
) -> bool:
    try:
        if type(identity) is not ServiceIdentity:
            return False
        a = parse_show(show)
        if (a["LoadState"] != "loaded" or a["ActiveState"] != "active" or
            a["MainPID"] != str(identity.pid) or
            a["InvocationID"] != identity.invocation_id or
            a["ControlGroup"] != CGROUP or
            a["DevicePolicy"] != "closed" or
            a["Restart"] != "no" or
            a["User"] != "harrypotter" or
            a["KillMode"] != "control-group"):
            return False
        if (identity.cgroup != CGROUP or identity.boot_id != boot_id or
            identity.pid <= 1 or
            proc_start_ticks(proc_stat) != identity.start_ticks or
            f"0::{CGROUP}" not in proc_cgroup.splitlines()):
            return False
        argv = [a for a in proc_cmdline.split(b"\0") if a]
        flags = [a.encode() for a in _fixed_flags()]
        if len(argv) != 2 + len(flags):
            return False
        if argv[1] != os.fsencode(MAIN) or argv[2:] != flags:
            return False
        # No accepting a different executable merely because its basename
        # happens to be "python": pin the exact venv command used by RM.
        if b"--cpu" in argv or argv[0] != os.fsencode(PYTHON):
            return False
        if amd_owners is None or identity.pid not in amd_owners:
            return False
        if any(type(pid) is not int or pid <= 1 or
               owner_cgroup(pid) != CGROUP for pid in amd_owners):
            return False
        return True
    except (ControllerBlocked, KeyError, ValueError, TypeError, OSError):
        return False

def trusted_host_inputs() -> list[str]:
    """No permission changes. Report blockers for future root-owned runtime."""
    problems: list[str] = []
    for p in (PYTHON, MAIN):
        try:
            x = p.stat()
            if not stat.S_ISREG(x.st_mode) or not os.access(p, os.R_OK):
                problems.append("missing/non-file runtime executable")
        except OSError:
            problems.append("missing runtime file " + str(p))
    for sub in ("input", "output", "temp", "user"):
        p = BASE / sub
        try:
            info = p.lstat()
            if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
                problems.append("unsafe private staging directory " + sub)
        except OSError:
            problems.append("missing private staging directory " + sub)
    return problems

def readonly_check() -> dict[str, object]:
    # Host runtime is currently modifiable by the harrypotter account:
    # this is acceptable for CPU DEV inspection, but NOT an OS isolation PASS.
    problems = trusted_host_inputs()
    try:
        main = MAIN.stat()
        runtime_mutable_by_executor = bool(
            main.st_uid == os.getuid() and main.st_mode & stat.S_IWUSR)
    except OSError:
        runtime_mutable_by_executor = True
    return {
        "gate": "PASS" if not problems else "BLOCKED",
        "problems": problems,
        "runtime_mutable_by_executor": runtime_mutable_by_executor,
        "production_os_isolation": "BLOCKED",
        "start_enabled": False,
        "systemd_mutated": False,
        "service_unit": UNIT,
        "staging": str(BASE),
        "runtime_memory_budget": "NOT_APPROVED",
        "gpu_reuse_safe": "NOT_VERIFIED",
    }

if __name__ == "__main__":
    if sys.argv[1:] != ["--check"]:
        raise SystemExit("Only read-only --check permitted; operator runner not installed.")
    info = readonly_check()
    print(json.dumps(info, indent=2, sort_keys=True))
    raise SystemExit(0 if info["gate"] == "PASS" else 3)
