#!/usr/bin/env python3
"""Read-only fail-closed predicates for restoring ComfyUI after live Qwen.

This is NOT a rollback runner. Its PASS-like decision is restricted to
process/model/descriptor preconditions, NOT AMD driver GPU_REUSE_SAFE.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
from urllib.request import urlopen

QWEN = "qwen3.6:35b-hermes64k"
DEV_UNIT = "ai-rm-comfy-ondemand-dev.service"
DEV_BASE = Path("/srv/ai-data/staging/comfy-fullchain-dev-20261024-guarded")


@dataclass(frozen=True)
class RestoreObservation:
    dev_unit_inactive: bool | None
    dev_mainpid_zero: bool | None
    dev_cgroup_empty: bool | None
    worker_identity_gone: bool | None
    gateway_dev_port_closed: bool | None
    comfy_dev_port_closed: bool | None
    ollama_models: tuple[str, ...] | None
    amd_device_owners: tuple[int, ...] | None


def require_valid_ollama_inventory(body: object) -> tuple[str, ...]:
    if not isinstance(body, dict):
        raise ValueError("invalid Ollama inventory")
    models = body.get("models")
    if not isinstance(models, list):
        raise ValueError("missing Ollama model list")
    names = []
    for value in models:
        if (not isinstance(value, dict) or not isinstance(value.get("name"), str)
                or not value["name"] or len(value["name"]) > 256):
            raise ValueError("invalid resident model record")
        names.append(value["name"])
    if len(names) != len(set(names)):
        raise ValueError("duplicate resident model")
    return tuple(names)


def classify_restore_gate(facts: RestoreObservation) -> dict[str, object]:
    """No implicit recovery after process disappearance or model unload."""
    reasons: list[str] = []
    for field in ("dev_unit_inactive", "dev_mainpid_zero", "dev_cgroup_empty",
                  "worker_identity_gone", "gateway_dev_port_closed",
                  "comfy_dev_port_closed"):
        if getattr(facts, field) is not True:
            reasons.append("NOT_VERIFIED_OR_BUSY:" + field)
    if facts.ollama_models is None:
        reasons.append("OLLAMA_RESIDENCY_UNKNOWN")
    elif any(model != QWEN for model in facts.ollama_models):
        reasons.append("UNEXPECTED_OLLAMA_MODEL")
    elif facts.ollama_models:
        reasons.append("QWEN_STILL_RESIDENT_REQUIRES_CONTROLLED_UNLOAD")
    if facts.amd_device_owners is None:
        reasons.append("AMD_GPU_OWNER_LIST_UNVERIFIED")
    elif facts.amd_device_owners:
        reasons.append("AMD_GPU_DESCRIPTORS_STILL_OPEN")

    return {
        "schema": 1,
        "restore_prerequisites": "PASS" if not reasons else "BLOCKED",
        "reasons": reasons,
        "gpu_reuse_safe": "NOT_VERIFIED",
        "driver_esafe": "NOT_VERIFIED",
        "production_restored": False,
        "permission_to_start_production_comfy":
            False,  # this check cannot authorize service mutations
    }


def _systemd_read(unit: str) -> tuple[bool | None, bool | None]:
    proc = subprocess.run([
        "/usr/bin/systemctl", "--system", "show", unit,
        "--property=ActiveState,MainPID", "--no-pager",
    ], capture_output=True, text=True, timeout=5, check=False)
    if proc.returncode:
        return None, None
    attrs = dict(line.split("=", 1) for line in proc.stdout.splitlines()
                 if "=" in line)
    try:
        return (attrs.get("ActiveState") == "inactive",
                int(attrs["MainPID"]) == 0)
    except (ValueError, KeyError):
        return None, None


def _port_closed(port: int) -> bool | None:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(.5)
            return sock.connect_ex(("127.0.0.1", port)) != 0
    except OSError:
        return None


def _process_gone() -> bool | None:
    """Future operator runner must persist boot_id and PID birthtime evidence."""
    file = DEV_BASE / "fullchain-worker-identity.json"
    if not file.is_file() or file.is_symlink():
        return None
    try:
        data = json.loads(file.read_text())
        pid, birth, boot = data["pid"], data["start_ticks"], data["boot_id"]
        if type(pid) is not int or pid <= 1 or type(birth) is not int or birth <= 0:
            return None
        if not isinstance(boot, str) or len(boot) != 36:
            return None
        if boot != Path("/proc/sys/kernel/random/boot_id").read_text().strip():
            return None
        p = Path("/proc") / str(pid)
        if not p.exists():
            return True
        current = int((p / "stat").read_text().rsplit(")", 1)[1].split()[19])
        return current != birth
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _read_model_names() -> tuple[str, ...] | None:
    try:
        with urlopen("http://127.0.0.1:11434/api/ps", timeout=3) as resp:
            return require_valid_ollama_inventory(json.load(resp))
    except (OSError, ValueError, TimeoutError):
        return None


def _gpu_owners_root_only() -> tuple[int, ...] | None:
    # A normal user may see an incomplete PID list for other service UIDs.
    if os.geteuid() != 0:
        return None
    try:
        out = subprocess.run(
            ["/usr/bin/fuser", "/dev/kfd", "/dev/dri/renderD128"],
            capture_output=True, text=True, timeout=6, check=False,
        )
        pids = tuple(sorted(int(v) for v in out.stdout.split() if v.isdecimal()))
        if out.returncode == 1 and not pids:
            return ()
        if out.returncode == 0 and pids:
            return pids
    except (OSError, ValueError, subprocess.TimeoutExpired):
        pass
    return None


def observe_readonly() -> RestoreObservation:
    unit_inactive, zero = _systemd_read(DEV_UNIT)
    cgroup = Path("/sys/fs/cgroup/system.slice") / DEV_UNIT / "cgroup.procs"
    try:
        cgroup_empty = (not cgroup.exists() or not cgroup.read_text().strip())
    except OSError:
        cgroup_empty = None
    return RestoreObservation(
        dev_unit_inactive=unit_inactive,
        dev_mainpid_zero=zero,
        dev_cgroup_empty=cgroup_empty,
        worker_identity_gone=_process_gone(),
        gateway_dev_port_closed=_port_closed(11656),
        comfy_dev_port_closed=_port_closed(11657),
        ollama_models=_read_model_names(),
        amd_device_owners=_gpu_owners_root_only(),
    )


if __name__ == "__main__":
    if sys.argv[1:] != ["--check"]:
        print("Usage: fullchain_rollback_gate_dev.py --check", file=sys.stderr)
        raise SystemExit(2)
    result = classify_restore_gate(observe_readonly())
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    raise SystemExit(0 if result["restore_prerequisites"] == "PASS" else 3)
