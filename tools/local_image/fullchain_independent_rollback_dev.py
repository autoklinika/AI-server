#!/usr/bin/env python3
"""Single-shot independent recovery algorithm for DEV fullchain.

No daemon, no scheduler. Tests exercise its operation ordering with a fake
backend. The CLI is deliberately --check-only until root-owned installation,
real-driver gate validation and separate operator approval.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import sys
from typing import Protocol

WATCHDOG_UNIT = "ai-rm-fullchain-rollback-20261024"
DEV_COMFY_UNIT = "ai-rm-comfy-ondemand-dev.service"
DEV_GATEWAY = "127.0.0.1:11656"
DEV_COMFY = "127.0.0.1:11657"
PROD_COMFY_UNIT = "comfyui.service"
PROD_GATEWAY_UNIT = "ai-gateway.service"
ROOT_OWNED_COPY = Path("/run/ai-rm-fullchain-recovery/rollback.py")

class RollbackBlocked(RuntimeError):
    pass

@dataclass(frozen=True)
class DriverEvidence:
    """External root monitor supplies these independently; not RM IDLE."""
    boot_matches_start: bool
    drm_card_present: bool
    kfd_present: bool
    amd_owner_free: bool
    no_amdgpu_reset_events: bool
    no_mes_errors_since_test: bool
    no_pcie_aer_errors_since_test: bool
    approved_driver_reuse_smoke: bool

def require_driver_evidence(evidence: DriverEvidence) -> None:
    if type(evidence) is not DriverEvidence:
        raise RollbackBlocked("trusted driver evidence not supplied")
    for name, value in vars(evidence).items():
        if type(value) is not bool or value is not True:
            raise RollbackBlocked("GPU reuse unsafe or unverified: "+name)

def watchdog_plan() -> tuple[str, ...]:
    """Command to be installed ONLY inside future approved root window."""
    return (
        "/usr/bin/systemd-run", "--system", "--on-active=12min",
        "--unit="+WATCHDOG_UNIT, "--service-type=exec",
        "/usr/bin/python3", str(ROOT_OWNED_COPY), "--execute",
    )

class RecoveryBackend(Protocol):
    def root_authority_verified(self) -> bool: ...
    def watchdog_armed(self) -> bool: ...
    def evidence_backup_exists(self) -> bool: ...
    def snapshot(self, label: str) -> None: ...
    def stop_captured_worker(self) -> None: ...
    def stop_dev_gateway(self) -> None: ...
    def stop_fixed_comfy_unit(self) -> None: ...
    def confirm_only_approved_processes_stopped(self) -> None: ...
    def drain_exact_qwen(self) -> None: ...
    def check_no_amd_owners(self) -> None: ...
    def driver_evidence(self) -> DriverEvidence: ...
    def restore_unit(self, unit: str) -> None: ...
    def check_production_smoke(self) -> None: ...
    def archive_evidence(self) -> None: ...
    def disarm_watchdog(self) -> None: ...
    def log(self, event: str) -> None: ...

def recovery_once(backend: RecoveryBackend) -> dict[str, object]:
    """Fail closed; never retry or clear marker on uncertain cleanup.

    Must be run from an independently armed *system* timer using a trusted,
    root-owned copy. This module itself does NOT expose executable mode.
    """
    events: list[str] = []
    def call(step: str, fn, *args):
        backend.log(step)
        events.append(step)
        return fn(*args)

    try:
        if not (
            backend.root_authority_verified()
            and backend.watchdog_armed()
            and backend.evidence_backup_exists()
        ):
            raise RollbackBlocked("untrusted root authority, watchdog or backup")
        call("SNAPSHOT_PRE", backend.snapshot, "pre-recovery")
        call("STOP_CAPTURED_WORKER", backend.stop_captured_worker)
        call("STOP_DEV_GATEWAY", backend.stop_dev_gateway)
        call("STOP_EXACT_DEV_COMFY_UNIT", backend.stop_fixed_comfy_unit)
        call("VERIFY_DEV_EXIT_CGROUP_PORTS", backend.confirm_only_approved_processes_stopped)
        call("DRAIN_ONLY_FENCED_QWEN", backend.drain_exact_qwen)
        call("VERIFY_AMD_OWNER_EMPTY", backend.check_no_amd_owners)
        call("VERIFY_DRIVER_E_SAFE", require_driver_evidence, backend.driver_evidence())
        # Archive the original negative/positive evidence before restoring
        # any production service. A failed archive must block restart.
        call("ARCHIVE_EVIDENCE", backend.archive_evidence)
        call("START_ORIGINAL_COMFY", backend.restore_unit, PROD_COMFY_UNIT)
        call("START_ORIGINAL_GATEWAY", backend.restore_unit, PROD_GATEWAY_UNIT)
        call("VERIFY_PRODUCTION_HEALTH", backend.check_production_smoke)
        call("SNAPSHOT_POST", backend.snapshot, "post-recovery")
        call("DISARM_INDEPENDENT_WATCHDOG", backend.disarm_watchdog)
        return {
            "schema": 1, "verdict": "SIMULATED_ROLLBACK_PASS",
            "steps": events,
            "gpu_reuse_safe": "NOT_VERIFIED_BY_THIS_ORCHESTRATOR",
            "recovery_marker": "ARCHIVED_BY_TRUSTED_BACKEND",
            "systemd_execution": "NONE_IN_THIS_LIBRARY",
        }
    except Exception as exc:
        try:
            backend.log("BLOCKED:" + type(exc).__name__)
        except Exception:
            pass
        return {
            "schema": 1, "verdict": "BLOCKED",
            "steps": events, "failure_class": type(exc).__name__,
            "gpu_reuse_safe": "NOT_VERIFIED",
            "recovery_marker": "MUST_REMAIN",
            "watchdog": "REMAIN_ARMED_FOR_OPERATOR_REVIEW",
            "production_restore": (
                "PARTIAL_OR_UNVERIFIED" if "START_ORIGINAL_COMFY" in events
                else "NOT_STARTED"
            ),
        }

def readonly_check() -> dict[str, object]:
    return {
        "schema": 1,
        "kind": "DEV_INDEPENDENT_RECOVERY_CODE_REVIEW_ONLY",
        "watchdog_unit": WATCHDOG_UNIT,
        "allowed_dev_unit": DEV_COMFY_UNIT,
        "allowed_production_units": [PROD_COMFY_UNIT, PROD_GATEWAY_UNIT],
        "runner_installed": False,
        "watchdog_armed": False,
        "root_authorized": False,
        "gpu_reuse_safe": "NOT_VERIFIED",
        "recovery_live_gate": "BLOCKED",
    }

if __name__ == "__main__":
    if sys.argv[1:] != ["--check"]:
        print("Only read-only --check; no --execute in this DEV worktree.",
              file=sys.stderr)
        raise SystemExit(3)
    print(json.dumps(readonly_check(), ensure_ascii=False, indent=2))
