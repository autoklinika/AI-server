"""Single fixed N5 ROCm hardware pilot, deliberately NOT an N1 GPU grant.

Run only in an explicit maintenance window, after owner services are stopped.
The one-shot marker remains permanently and the result NEVER authorizes reuse.
No HTTP route, service manipulation, fallback runtime or arbitrary CLI command.
"""
from __future__ import annotations

import fcntl
import json
import os
from pathlib import Path
import subprocess
from time import time

from .managed_worker_observer import SyntheticCPU, WorkerObserver
from .rocm_test_worker import EXPECTED_PCI, WORKLOAD
from .rocm_managed_adapter import FIXED_COMMAND

SERVICES = (
    "ai-bridge-analysis.timer", "ai-gateway.service", "ai-bridge.service",
    "comfyui.service", "ollama.service",
)
DEV_ROOT = Path("/srv/ai-data/evaluation/rm-rocm-hardware-pilot")


class PilotBlocked(RuntimeError):
    pass


def check_readiness(*, query=None, kfd=None, gpu_users=None, device_root=None):
    """Fail closed on all unknown/unexpected states; cannot certify global E_safe."""
    def default_query(name):
        return subprocess.run(["systemctl", "is-active", name], capture_output=True,
                              text=True, timeout=3).stdout.strip()
    query = query or default_query
    for service in SERVICES:
        if query(service) != "inactive":
            raise PilotBlocked(f"service must be inactive: {service}")
    pci = (device_root or Path("/sys/bus/pci/devices")) / EXPECTED_PCI
    if ((pci / "vendor").read_text().strip() != "0x1002" or
            (pci / "device").read_text().strip() != "0x150e"):
        raise PilotBlocked("PCI identity mismatch")
    if kfd is None:
        kfd = sorted(p.name for p in Path("/sys/class/kfd/kfd/proc").iterdir())
    if kfd:
        raise PilotBlocked("KFD context(s) remain: " + ",".join(kfd[:10]))
    if gpu_users is None:
        p = subprocess.run(["fuser", "/dev/kfd", "/dev/dri/renderD128"],
                           capture_output=True, text=True, timeout=4)
        if p.returncode not in (0, 1):
            raise PilotBlocked("GPU FD inventory unavailable")
        gpu_users = p.stdout.strip()
    if gpu_users:
        raise PilotBlocked("GPU device holder(s) remain: " + str(gpu_users)[:150])
    return {"pci": EXPECTED_PCI, "kfd": "none-visible", "fuser": "none-visible",
            "services": "inactive", "reuse_safe": "NOT_VERIFIED"}


class FixedROCmRuntime(SyntheticCPU):
    """Trusted, hardcoded child command; output captured only in fixed files."""
    def __init__(self, folder: Path):
        self.folder = folder

    def spawn(self):
        out = (self.folder / "worker.stdout").open("xb")
        err = (self.folder / "worker.stderr").open("xb")
        try:
            return subprocess.Popen(FIXED_COMMAND, shell=False,
                                    start_new_session=True, stdin=subprocess.DEVNULL,
                                    stdout=out, stderr=err, close_fds=True)
        finally:
            out.close()
            err.close()


def run_once(folder: Path, *, preflight=check_readiness, runtime_factory=FixedROCmRuntime,
             timeout=120.0):
    if folder.exists():
        raise PilotBlocked("attempt already exists: refusing replay")
    folder.parent.mkdir(parents=True, exist_ok=True)
    lock = (folder.parent / ".rocm-pilot.lock").open("a")
    try:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as exc:
        raise PilotBlocked("another hardware pilot is running") from exc
    try:
        # Check before and after creating durable ownership.
        check1 = preflight()
        folder.mkdir(mode=0o700)
        marker = folder / "ownership.dirty"
        runtime = runtime_factory(folder)
        observer = WorkerObserver(marker, runtime=runtime, marker_label="HARDWARE-PILOT")
        result = {"schema": 1, "workload": WORKLOAD, "pci_bdf": EXPECTED_PCI,
                  "start_epoch": time(), "result": "DIRTY",
                  "gpu_reuse_safe": "NOT_VERIFIED", "preflight": check1}
        child = None
        try:
            result["recheck"] = preflight()
            identity = observer.start()
            child = getattr(observer, "_child", None)
            result["pid"] = identity.pid
            result["boot_id"] = identity.boot_id
            result["process_status"] = observer.observe(timeout=timeout)
            if result["process_status"] != "PROCESS_CLOSED":
                raise PilotBlocked("worker did not close cleanly")
            if result["process_status"] == "PROCESS_CLOSED":
                raw = (folder / "worker.stdout").read_bytes()
                if len(raw) > 1024:
                    raise PilotBlocked("oversized worker output")
                def unique(pairs):
                    if len(dict(pairs)) != len(pairs):
                        raise PilotBlocked("duplicate result fields")
                    return dict(pairs)
                payload = json.loads(raw, object_pairs_hook=unique)
                expected = {"schema": 1, "workload": WORKLOAD,
                            "pci_bdf": EXPECTED_PCI, "local_synced": True,
                            "status": "WORKER_LOCAL_SYNC"}
                if payload != expected or type(payload["local_synced"]) is not bool:
                    raise PilotBlocked("worker result did not pass fixed validation")
                result["worker_status"] = "WORKER_LOCAL_SYNC"
            result["postflight"] = preflight()
            if result.get("worker_status") == "WORKER_LOCAL_SYNC":
                result["result"] = "PROCESS_CLOSED"
        except BaseException as exc:
            result["error"] = type(exc).__name__
            if child is not None and child.poll() is None:
                child.terminate()  # Child we own; no broad process/group kill.
                try:
                    child.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    result["error"] += ":child_still_live"
            raise
        finally:
            result["finish_epoch"] = time()
            receipt = folder / "result.json"
            with receipt.open("x") as dst:
                json.dump(result, dst, sort_keys=True, indent=2)
                dst.flush()
                os.fsync(dst.fileno())
            fd = os.open(folder, os.O_DIRECTORY | os.O_RDONLY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        return result
    finally:
        fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
        lock.close()


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--attempt", required=True,
                        help="single unique alphanumeric identifier; never repeated")
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    import re
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,47}", args.attempt):
        parser.error("invalid attempt ID")
    if not args.execute:
        print(json.dumps({"state": "DRY_RUN", "preflight": check_readiness()}))
        return
    output = run_once(DEV_ROOT / args.attempt)
    print(json.dumps(output, sort_keys=True))


if __name__ == "__main__":
    main()
