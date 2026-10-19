"""RM OS GPU access boundary: read-only evidence; never issues N1 grants.

An allowed state must be demonstrated by an independent *system* manager
negative probe. A user-manager DevicePolicy setting, an idle KFD inventory, or
an absent owner is NEVER evidence of access enforcement. The current function
always reports GPU admission blocked, even when its scoped diagnostics pass.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import subprocess
from typing import Callable

GPU = ("/dev/kfd", "/dev/dri/renderD128")
SERVICE_UNITS = (
    "ai-gateway.service",
    "ai-bridge.service",
    "ollama.service",
    "comfyui.service",
)
TIMER_UNITS = ("ai-bridge-analysis.timer",)
WORKER_UNIT = "ai-vision-execution@rm-gpu-probe.service"
EXPECTED_PCI = "0000:c6:00.0"


@dataclass(frozen=True)
class Boundary:
    schema: int
    decision: str
    os_device_access: str
    driver_reuse: str
    checks: dict[str, object]

    def __bool__(self):
        raise TypeError("GPU boundary observations never imply an N1 grant")

    def as_dict(self):
        return {
            "schema": self.schema, "decision": self.decision,
            "os_device_access": self.os_device_access,
            "driver_reuse": self.driver_reuse, "checks": self.checks,
        }


def _command(*args: str, timeout: int = 4) -> subprocess.CompletedProcess:
    return subprocess.run(args, text=True, capture_output=True, timeout=timeout,
                          check=False)


def _access(path: str) -> str:
    """Open/close only. No ioctls or computation. Fail closed on exceptions."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NONBLOCK)
    except OSError as exc:
        return f"DENIED_ERRNO_{exc.errno}"
    else:
        os.close(fd)
        return "OPEN_SUCCEEDED"


def _unit(name: str, command: Callable = _command) -> dict[str, object]:
    fields = ("LoadState,ActiveState" if name.endswith(".timer") else
              "LoadState,ActiveState,MainPID,DevicePolicy,PrivateDevices,User")
    p = command("systemctl", "show", name, "--no-pager",
                "--property=" + fields)
    if p.returncode != 0:
        return {"inspection": "UNKNOWN"}
    keys = {}
    for line in p.stdout.splitlines():
        if "=" not in line:
            return {"inspection": "UNKNOWN"}
        a, b = line.split("=", 1)
        if a in keys:
            return {"inspection": "UNKNOWN"}
        keys[a] = b
    required = ({"LoadState", "ActiveState"} if name.endswith(".timer") else
                {"LoadState", "ActiveState", "MainPID", "DevicePolicy",
                 "PrivateDevices", "User"})
    if not required <= keys.keys():
        return {"inspection": "UNKNOWN"}
    return keys


def inspect(*, access: Callable[[str], str] = _access,
            unit: Callable[[str], dict] = _unit,
            uid: Callable[[], int] = os.geteuid,
            groups: Callable[[], list[int]] = os.getgroups,
            pci_root: Path = Path("/sys/bus/pci/devices")) -> Boundary:
    checks: dict[str, object] = {"pci": "UNKNOWN", "units": {},
                                 "device_open": {}, "role": {},
                                 "reason": "NO_TRUSTED_SYSTEM_MANAGER_DENIAL"}
    try:
        pci = pci_root / EXPECTED_PCI
        if ((pci / "vendor").read_text().strip() == "0x1002"
                and (pci / "device").read_text().strip() == "0x150e"):
            checks["pci"] = EXPECTED_PCI
    except OSError:
        pass
    try:
        checks["role"] = {"effective_uid": uid(), "supplementary_gids": groups()}
    except (OSError, ValueError):
        checks["role"] = {"status": "UNKNOWN"}
    for path in GPU:
        try:
            checks["device_open"][path] = access(path)
        except Exception:
            checks["device_open"][path] = "UNKNOWN"
    for name in SERVICE_UNITS + TIMER_UNITS + (WORKER_UNIT,):
        try:
            checks["units"][name] = unit(name)
        except Exception:
            checks["units"][name] = {"inspection": "UNKNOWN"}
    service_off = (all(
        checks["units"][name].get("ActiveState") == "inactive"
        and checks["units"][name].get("MainPID") == "0"
        for name in SERVICE_UNITS
    ) and all(checks["units"][name].get("ActiveState") == "inactive"
              for name in TIMER_UNITS))
    checks["maintenance_services_stopped"] = service_off
    openable = any(checks["device_open"][p] == "OPEN_SUCCEEDED" for p in GPU)
    checks["unmanaged_process_can_open_gpu"] = openable
    checks["worker_system_unit_installed"] = (
        checks["units"][WORKER_UNIT].get("LoadState") == "loaded")
    # A user-shell probe is useful evidence of a bypass, but its inability to
    # open a device is NOT evidence that other authorized UIDs cannot open it.
    # System-manager cgroup eBPF enforcement and all external principals need
    # independent verification; never emit a positive physical admission.
    return Boundary(1, "BLOCKED", "UNVERIFIED_OPEN_BYPASS" if openable
                    else "UNVERIFIED", "NOT_VERIFIED", checks)


def main() -> int:
    result = inspect()
    print(json.dumps(result.as_dict(), indent=2, sort_keys=True))
    return 2  # no admission even if all observational checks are nominal


if __name__ == "__main__":
    raise SystemExit(main())
