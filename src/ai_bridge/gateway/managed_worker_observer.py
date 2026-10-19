"""N5 DEV SIMULATION: observe one fixed CPU child, never authorize GPU reuse.

No Gateway wiring, SafetyAdapter, signals, arbitrary commands or release API.
Single synchronous supervisor owner. A durable attempt marker is never cleared:
recreating the observer cannot restart that attempt, even after a clean exit.
This is not a containment boundary for descendants or delegated device handles.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import math
import os
from pathlib import Path
import subprocess
import sys
from typing import Protocol


@dataclass(frozen=True)
class Identity:
    boot_id: str
    pid: int
    birth_ticks: int
    session: int
    process_group: int
    scope: str  # Supervisor attempt name, NOT a kernel cgroup attestation.


class Runtime(Protocol):
    def spawn(self): ...
    def identity(self, child, scope: str) -> Identity: ...
    def wait(self, child, timeout: float) -> int: ...


class SyntheticCPU:
    """Only a short, finite stdlib CPU program; no worker-supplied evidence."""

    def spawn(self):
        return subprocess.Popen(
            [sys.executable, "-I", "-S", "-c",
             "import time; time.sleep(0.15); sum(i*i for i in range(10000))"],
            start_new_session=True, stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            close_fds=True,
        )

    def identity(self, child, scope):
        # Do not poll/reap here: a direct child's zombie preserves its identity
        # until wait(), including a child that exits before this read.
        fields = Path(f"/proc/{child.pid}/stat").read_text().rsplit(")", 1)[1].split()
        return Identity(Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
                        child.pid, int(fields[19]), int(fields[3]), int(fields[2]), scope)

    def wait(self, child, timeout):
        return child.wait(timeout=timeout)


class WorkerObserver:
    """Observe-only fallback (task D); dirty means unresolved attempt ownership.

    wait() always reaps only our original child handle. Cancellation/timeout and
    identity failures latch DIRTY; later reap cannot turn them into success.
    No attach-by-PID or restart operation. Marker directory must be trusted DEV
    workspace/tmp storage. Markers are conservative tombstones, not an RM journal.
    """

    def __init__(self, marker: Path, *, runtime: Runtime | None = None,
                 marker_label: str = "SIMULATION"):
        if marker_label not in ("SIMULATION", "HARDWARE-PILOT"):
            raise ValueError("unsupported marker label")
        self._marker_label = marker_label
        self._marker = marker
        self._runtime = runtime if runtime is not None else SyntheticCPU()
        self._child = None
        self._identity = None
        self._state = "NEW"
        self._reaped = False

    @property
    def state(self):
        return self._state

    @property
    def identity(self):
        return self._identity

    def start(self) -> Identity:
        if self._state != "NEW":
            raise RuntimeError("attempt cannot start/restart")
        self._state = "DIRTY"  # Before persistence or spawn, including exceptions.
        with self._marker.open("x") as record:
            record.write(f"{self._marker_label}: attempt reserved; reuse forbidden\n")
            record.flush()
            os.fsync(record.fileno())
        fd = os.open(self._marker.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
        self._child = self._runtime.spawn()
        identity = self._runtime.identity(self._child, self._marker.name)
        if (identity.pid != self._child.pid or identity.pid <= 1
                or identity.birth_ticks <= 0 or not identity.boot_id
                or identity.session != identity.pid or identity.process_group != identity.pid
                or identity.scope != self._marker.name):
            raise RuntimeError("original start identity unavailable")
        self._identity = identity
        with self._marker.open("a") as record:
            record.write(json.dumps(identity.__dict__, sort_keys=True) + "\n")
            record.flush()
            os.fsync(record.fileno())
        self._state = "RUNNING"
        return identity

    def cancel(self):
        # Observe-only: no signals, even on a known PID. Finite CPU child exits
        # naturally; caller must still reap it via observe().
        self._state = "DIRTY"

    def observe(self, *, timeout: float = 2.0) -> str:
        if type(timeout) not in (float, int) or not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("timeout must be finite and positive")
        if self._child is None:
            raise RuntimeError("no owned child handle")
        if self._reaped:
            return self._state
        try:
            if self._runtime.identity(self._child, self._marker.name) != self._identity:
                self._state = "DIRTY"
        except Exception:
            self._state = "DIRTY"
        except BaseException:
            self._state = "DIRTY"
            raise
        try:
            code = self._runtime.wait(self._child, timeout)
            self._reaped = True
            if self._state == "RUNNING" and type(code) is int and code == 0:
                self._state = "PROCESS_CLOSED"
            else:
                self._state = "DIRTY"
        except BaseException:
            self._state = "DIRTY"
            raise
        return self._state
