"""Read-only hardware lifecycle evidence for a single fixed EXCLUSIVE N5 worker.

It is NOT N1 admission, a GPU reuse certificate, or a privileged GPU owner.
Requires previously stopped services and preserves the durable DIRTY marker.
"""
from __future__ import annotations

import fcntl
import json
import os
from pathlib import Path
import select
import subprocess
from time import time

from .managed_worker_observer import SyntheticCPU, WorkerObserver
from .rocm_maintenance_pilot import DEV_ROOT, PilotBlocked, check_readiness
from .rocm_test_worker import EXPECTED_PCI, WORKLOAD

_COMMAND = ("/opt/comfyui/venv/bin/python", "-I", "-u",
            str(Path(__file__).with_name("rocm_lifecycle_worker.py").resolve()))
_EXPECTED = {"schema": 1, "workload": WORKLOAD, "pci_bdf": EXPECTED_PCI,
             "local_synced": True, "status": "WORKER_LOCAL_SYNC"}


class LifecycleRuntime(SyntheticCPU):
    def __init__(self, folder: Path):
        self.folder = folder

    @staticmethod
    def line(child, timeout=10.0):
        if not select.select([child.stdout], [], [], timeout)[0]:
            raise PilotBlocked("worker output timeout")
        raw = child.stdout.readline()
        if not raw or len(raw) > 1024:
            raise PilotBlocked("worker output unavailable")
        return raw

    def spawn(self):
        stderr = (self.folder / "worker.stderr").open("xb")
        try:
            child = subprocess.Popen(_COMMAND, stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, stderr=stderr,
                                     start_new_session=True, close_fds=True)
        finally:
            stderr.close()
        try:
            if self.line(child, 5) != b"READY\n" or child.poll() is not None:
                raise PilotBlocked("worker failed to park")
            return child
        except BaseException:
            self.abort(child)
            raise

    @staticmethod
    def activate(child):
        if child.poll() is not None:
            raise PilotBlocked("worker died before GPU activation")
        child.stdin.write(b"G")
        child.stdin.flush()

    def read_result(self, child):
        raw = self.line(child)
        def unique(items):
            result = dict(items)
            if len(result) != len(items):
                raise PilotBlocked("duplicate worker result fields")
            return result
        value = json.loads(raw, object_pairs_hook=unique)
        if value != _EXPECTED or type(value.get("local_synced")) is not bool:
            raise PilotBlocked("invalid local GPU completion evidence")
        return value

    @staticmethod
    def finish(child):
        if child.poll() is not None:
            raise PilotBlocked("worker exited before owner inspection")
        child.stdin.write(b"X")
        child.stdin.flush()
        child.stdin.close()

    @staticmethod
    def abort(child):
        if child is not None and child.poll() is None:
            child.terminate()  # Only original child, never arbitrary PID.
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                raise PilotBlocked("worker still alive after SIGTERM; manual recovery required")


def inspect_live_holder(pid, *, kfd_root=Path("/sys/class/kfd/kfd/proc"),
                        fuser=None):
    kfd = sorted(int(x.name) for x in kfd_root.iterdir() if x.name.isdecimal())
    if fuser is None:
        p = subprocess.run(["fuser", "/dev/kfd", "/dev/dri/renderD128"],
                           capture_output=True, text=True, timeout=4)
        if p.returncode not in (0, 1):
            raise PilotBlocked("live owner inventory unavailable")
        fuser = p.stdout
    try:
        owners = sorted({int(x) for x in fuser.split()})
    except ValueError as exc:
        raise PilotBlocked("invalid fuser owner data") from exc
    if (pid not in kfd and pid not in owners):
        raise PilotBlocked("active worker GPU context was not observed")
    if set(kfd + owners) - {pid}:
        raise PilotBlocked("foreign GPU context/owner observed")
    return {"worker_pid": pid, "kfd_processes": kfd, "device_fd_owners": owners,
            "status": "WORKER_OWNER_OBSERVED", "reuse_safe": "NOT_VERIFIED"}


def run_once(folder: Path, *, preflight=check_readiness,
             runtime_factory=LifecycleRuntime, live_inspector=inspect_live_holder):
    if folder.exists():
        raise PilotBlocked("attempt already exists")
    folder.parent.mkdir(parents=True, exist_ok=True)
    with (folder.parent / ".rocm-lifecycle.lock").open("a") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        before = preflight()
        folder.mkdir(mode=0o700)
        runtime = runtime_factory(folder)
        observer = WorkerObserver(folder / "ownership.dirty", runtime=runtime,
                                  marker_label="HARDWARE-PILOT")
        child = None
        report = {"schema": 1, "start_epoch": time(),
                  "workload": WORKLOAD, "pci": EXPECTED_PCI,
                  "outcome": "DIRTY", "gpu_reuse_safe": "NOT_VERIFIED",
                  "preflight": before}
        try:
            identity = observer.start()
            child = observer._child
            report["pid"] = identity.pid
            report["boot_id"] = identity.boot_id
            report["parked_recheck"] = preflight()
            runtime.activate(child)
            report["worker_result"] = runtime.read_result(child)
            report["live_owner"] = live_inspector(identity.pid)
            runtime.finish(child)
            report["process"] = observer.observe(timeout=10)
            if report["process"] != "PROCESS_CLOSED":
                raise PilotBlocked("worker termination unverified")
            report["postflight"] = preflight()
            report["outcome"] = "WORKER_LOCAL_SYNC_AND_CLOSED"
        except BaseException as exc:
            report["error"] = type(exc).__name__
            observer.cancel()
            raise
        finally:
            try:
                runtime.abort(child or observer._child)
            finally:
                report["finish_epoch"] = time()
                with (folder / "result.json").open("x") as fh:
                    json.dump(report, fh, indent=2, sort_keys=True)
                    fh.flush()
                    os.fsync(fh.fileno())
                fd = os.open(folder, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(fd)
                finally:
                    os.close(fd)
        return report


def main():
    import argparse
    import re
    parser = argparse.ArgumentParser()
    parser.add_argument("--attempt", required=True)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,47}", args.attempt):
        parser.error("bad attempt id")
    if not args.execute:
        print(json.dumps({"state": "READ_ONLY_PREFLIGHT", "preflight": check_readiness()}))
        return
    print(json.dumps(run_once(DEV_ROOT / args.attempt), sort_keys=True))


if __name__ == "__main__":
    main()
