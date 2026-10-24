#!/usr/bin/env python3
"""DEV only: bounded, injectable Qwen unload gate for an authorized rollback.

No global RM state, scheduler, or daemon is introduced. The function does not
start/stop systemd; no live unload is allowed by this CLI. A future root-owned
operator-only maintenance runner must supply the verified lifecycle fence and
the exact local Ollama transport.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import sys
from typing import Callable
from urllib.request import urlopen

QWEN = "qwen3.6:35b-hermes64k"
OLLAMA_CGROUP = "/system.slice/ollama.service"
OLLAMA_URL = "http://127.0.0.1:11434"


class ModelDrainBlocked(RuntimeError):
    """Fail-closed: retain the recovery marker and RM reservation."""


@dataclass(frozen=True)
class DrainFence:
    """Captured independently by the privileged operator's maintenance runner."""
    worker_identity_gone: bool
    gateway_dev_port_closed: bool
    comfy_dev_port_closed: bool
    comfy_dev_unit_inactive: bool
    comfy_dev_mainpid_zero: bool
    comfy_dev_cgroup_empty: bool
    watchdog_armed: bool
    recovery_marker_present: bool
    production_comfy_inactive: bool
    production_gateway_inactive: bool
    ollama_unit_active: bool


def require_preconditions(fence: DrainFence) -> None:
    if type(fence) is not DrainFence:
        raise ModelDrainBlocked("untrusted Qwen drain fence")
    # All eleven independently measured predicates are required. The exact
    # dataclass schema is the allowlist; do not infer trust from suffixes.
    for name, value in vars(fence).items():
        if type(value) is not bool or value is not True:
            raise ModelDrainBlocked("Qwen drain fenced: " + name)


def _names(response: object) -> tuple[str, ...]:
    if not isinstance(response, dict) or not isinstance(response.get("models"), list):
        raise ModelDrainBlocked("Ollama inventory unavailable or malformed")
    result: list[str] = []
    for item in response["models"]:
        if (not isinstance(item, dict) or
                not isinstance(item.get("name"), str) or
                not item["name"] or len(item["name"]) > 256):
            raise ModelDrainBlocked("untrusted Ollama resident model")
        result.append(item["name"])
    if len(set(result)) != len(result):
        raise ModelDrainBlocked("duplicate resident model")
    if any(item != QWEN for item in result):
        raise ModelDrainBlocked("foreign or WVC model must not be unloaded")
    return tuple(result)


def _owner_groups_trusted(
    pids: tuple[int, ...] | None,
    process_cgroup: Callable[[int], str | None],
) -> bool:
    if pids is None or any(type(pid) is not int or pid <= 1 for pid in pids):
        return False
    return all(process_cgroup(pid) in (
        OLLAMA_CGROUP,
        # A member of the Ollama service is not an unrelated bypass process.
        # Reject sibling services and unexpected user cgroups.
    ) for pid in pids)


def drain_qwen_with_fence(
    *,
    fence: DrainFence,
    read_models: Callable[[], object],
    unload_exact_qwen: Callable[[str], None],
    read_amd_pids: Callable[[], tuple[int, ...] | None],
    process_cgroup: Callable[[int], str | None],
    monotonic: Callable[[], float],
    sleep: Callable[[float], None],
    deadline_seconds: float = 30.0,
    poll_seconds: float = .25,
) -> dict[str, object]:
    """May unload only the exact Qwen, after *independent* operator fencing.

    Raises and leaves recovery in the caller's hands on any ambiguous evidence.
    Does not signal processes, restart services, or clear markers.
    """
    require_preconditions(fence)
    if not 1 <= deadline_seconds <= 120 or not .01 <= poll_seconds <= 2:
        raise ModelDrainBlocked("invalid bounded timeout/poll")
    starts = monotonic()
    initial = _names(read_models())
    holders = read_amd_pids()

    if initial:
        if not _owner_groups_trusted(holders, process_cgroup):
            raise ModelDrainBlocked("unverified or foreign AMD GPU device owner")
        if monotonic() - starts >= deadline_seconds:
            raise ModelDrainBlocked("model drain deadline expired before unload")
        # Exactly one allowed model name, never empty/unrecognized/foreign.
        unload_exact_qwen(QWEN)
    elif holders is None or holders:
        # /api/ps empty by itself is not proof of a free AMD device.
        raise ModelDrainBlocked("AMD owner not empty or unverified despite empty Ollama")

    seen_empty = 0
    while monotonic() - starts < deadline_seconds:
        model_names = _names(read_models())
        if model_names:
            seen_empty = 0
        else:
            # Two spaced observations prevent a single stale /api/ps from passing.
            seen_empty += 1
        if seen_empty >= 2:
            owners = read_amd_pids()
            if owners is None or owners:
                raise ModelDrainBlocked("AMD descriptors not independently cleared")
            return {
                "schema": 1,
                "model": QWEN,
                "initially_resident": bool(initial),
                "model_unloaded": True,
                "amd_descriptors_empty": True,
                "gpu_reuse_safe": "NOT_VERIFIED",
                "driver_esafe": "NOT_VERIFIED",
                "recovery_marker_cleared": False,
                "production_started": False,
                "verdict": "MODEL_DRAIN_AND_DESCRIPTOR_GATE_PASS",
            }
        sleep(poll_seconds)
    raise ModelDrainBlocked("model drain deadline expired, recovery fence retained")


def read_only_inventory() -> dict[str, object]:
    try:
        with urlopen(OLLAMA_URL + "/api/ps", timeout=3) as handle:
            names = _names(json.load(handle))
        status = "QWEN_PRESENT_NO_ACTION" if names else "NO_QWEN_RESIDENT"
    except (OSError, ValueError, ModelDrainBlocked) as exc:
        status = "BLOCKED:" + type(exc).__name__
    return {
        "mode": "READ_ONLY", "status": status,
        "model": QWEN, "unload_executed": False,
        "gpu_reuse_safe": "NOT_VERIFIED",
        "operator_live_restore_authorized": False,
    }


if __name__ == "__main__":
    if sys.argv[1:] != ["--check"]:
        print("Only --check is exposed. Model drain requires approved operator harness.",
              file=sys.stderr)
        raise SystemExit(2)
    result = read_only_inventory()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if not result["status"].startswith("BLOCKED:") else 3)
