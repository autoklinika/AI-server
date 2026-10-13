"""Shared Resource Manager adapter for local Vision benchmark processes.

DEV-only, gated behind AI_BRIDGE_GATEWAY_VISION_EXTERNAL_ENABLED. Reuses
the existing Gateway lease and GPU residency state machine; NO scheduler
or direct GPU access outside the admitted external-use interval.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time
from urllib.request import Request, urlopen


class VisionExecutionError(RuntimeError):
    pass


def call(base: str, method: str, path: str, payload: dict | None = None) -> dict:
    raw = json.dumps(payload).encode() if payload is not None else None
    req = Request(base + path, method=method, data=raw,
                  headers={"Content-Type": "application/json"} if raw else {})
    with urlopen(req, timeout=6) as resp:
        return json.load(resp)


def _stop_group(proc: subprocess.Popen) -> None:
    if proc.poll() is None:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            proc.wait(timeout=4)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            proc.wait(timeout=5)


def _verify_group_gone(pgid: int) -> None:
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return
    raise VisionExecutionError("process group is not empty: GPU ownership cannot be released")


class VisionRMExecutor:
    def __init__(self, *, base: str = "http://127.0.0.1:11435"):
        if not (base.startswith("http://127.0.0.1:") or base.startswith("http://localhost:")):
            raise ValueError("Gateway must be loopback")
        self.base = base.rstrip("/")

    def execute(self, *, python: Path, script: Path, args: list[str], log: Path,
                max_seconds: float = 110, queue_timeout_seconds: float = 120) -> dict:
        if max_seconds < 10 or queue_timeout_seconds < 1:
            raise ValueError("invalid timeouts")
        if log.exists():
            raise FileExistsError("refuse to overwrite executor log")
        log.parent.mkdir(parents=True, exist_ok=True)
        lease_id = None
        use_id = None
        task = None
        stop = threading.Event()
        heartbeat_errors: list[str] = []
        heartbeat_thread = None
        read_fd, write_fd = os.pipe()
        started = time.monotonic()

        def keep_alive():
            while not stop.wait(5):
                if lease_id:
                    try:
                        response = call(self.base, "POST", f"/resource/leases/{lease_id}/heartbeat")
                        if response.get("state") not in ("active", "queued"):
                            raise VisionExecutionError("lease is not active/queued")
                    except Exception as exc:
                        heartbeat_errors.append(type(exc).__name__)
                        stop.set()

        try:
            with log.open("x", encoding="utf-8") as output:
                worker = Path(__file__).with_name("vision_worker_gate.py")
                task = subprocess.Popen(
                    [str(python), str(worker),
                     "--gate-fd", str(read_fd),
                     "--gateway", self.base,
                     "--python", str(python),
                     "--script", str(script), "--", *args],
                    pass_fds=(read_fd,), stdin=subprocess.DEVNULL,
                    stdout=output, stderr=subprocess.STDOUT,
                    start_new_session=True, close_fds=True,
                )
                os.close(read_fd)
                read_fd = -1
                response = call(self.base, "GET", "/status")
                if response.get("admission_blocked") or response.get("gpu_residency", {}).get("recovery_required"):
                    raise VisionExecutionError("Resource Manager unavailable")
                reservation = call(self.base, "POST", "/resource/leases", {
                    "source": "vision-benchmark-dev",
                    "workload": "vision-benchmark",
                    "priority_class": "background",
                })
                lease_id = reservation["lease_id"]
                heartbeat_thread = threading.Thread(target=keep_alive, daemon=True)
                heartbeat_thread.start()

                # Wait for shared queue admission. The child remains parked.
                while reservation.get("state") != "active":
                    if heartbeat_errors or task.poll() is not None:
                        raise VisionExecutionError("lost queued reservation/parked worker")
                    if time.monotonic()-started > queue_timeout_seconds:
                        raise VisionExecutionError("Vision resource admission timed out")
                    time.sleep(0.25)
                    reservation = call(self.base, "GET", f"/resource/leases/{lease_id}")

                use = call(self.base, "POST", f"/resource/leases/{lease_id}/uses", {
                    "provider": "vision-local", "capability": "image-analysis",
                    "worker_pid": task.pid,
                })
                use_id = use["use_id"]
                with os.fdopen(write_fd, "w", encoding="utf-8") as gate:
                    gate.write(json.dumps({"lease_id": lease_id, "use_id": use_id}) + "\n")
                    gate.flush()
                write_fd = -1

                # Bound work and heartbeat. Do not permit LLM dispatch until
                # the child and its process group have exited.
                run_started = time.monotonic()
                while task.poll() is None:
                    if heartbeat_errors:
                        raise VisionExecutionError("Resource Manager heartbeat lost")
                    if time.monotonic()-run_started > max_seconds:
                        raise VisionExecutionError("Vision GPU worker exceeded time limit")
                    time.sleep(0.2)
                code = task.wait()
                _verify_group_gone(task.pid)
                # Always perform verified GPU cleanup, even if worker failed.
                cleanup = call(self.base, "DELETE", f"/resource/leases/{lease_id}/uses/{use_id}")
                if cleanup != {"released": True}:
                    raise VisionExecutionError("GPU cleanup was not verified")
                use_id = None
                if code != 0:
                    raise VisionExecutionError(f"Vision worker exit={code}")
                return {"status": "completed", "elapsed_seconds": round(time.monotonic()-started, 3),
                        "exit_code": code, "gateway_queue_used": True}
        finally:
            stop.set()
            if write_fd >= 0:
                os.close(write_fd)
            if read_fd >= 0:
                os.close(read_fd)
            if task is not None:
                _stop_group(task)
                try:
                    _verify_group_gone(task.pid)
                except VisionExecutionError:
                    # Do not fabricate clean GPU evidence; the RM vision-use pin
                    # remains and recovery is an explicit operator action.
                    raise
            # In fail cases only attempt cleanup after all worker processes exited.
            if lease_id is not None and use_id is not None:
                try:
                    call(self.base, "DELETE", f"/resource/leases/{lease_id}/uses/{use_id}")
                except Exception:
                    pass
            if lease_id is not None:
                try:
                    call(self.base, "DELETE", f"/resource/leases/{lease_id}")
                except Exception:
                    pass
            if heartbeat_thread:
                heartbeat_thread.join(timeout=2)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--python", type=Path, required=True)
    p.add_argument("--script", type=Path, required=True)
    p.add_argument("--log", type=Path, required=True)
    p.add_argument("--max-seconds", type=int, default=110)
    p.add_argument("args", nargs=argparse.REMAINDER)
    opts = p.parse_args()
    args = opts.args[1:] if opts.args[:1] == ["--"] else opts.args
    report = VisionRMExecutor().execute(
        python=opts.python, script=opts.script, args=args, log=opts.log,
        max_seconds=opts.max_seconds)
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
