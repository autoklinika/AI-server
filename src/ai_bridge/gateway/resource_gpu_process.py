"""P2-A3 partial NVIDIA compute-process observation; no RM ownership authority.

An nvidia-smi compute row is NOT a complete process inventory, a lease, a GPU
context closure proof or a memory reservation. AMD process attribution is not
implemented by this collector. One-shot I/O only; no import-time probes.
"""

from __future__ import annotations

import re
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .resource_hardware import HardwareReading

_UUID = re.compile(r"GPU-[a-zA-Z0-9-]{8,128}")
_MAX_OUTPUT = 32 * 1024
_MAX_PROCESSES = 256
_QUERY = (
    "/usr/bin/nvidia-smi",
    "--query-compute-apps=gpu_uuid,pid,used_gpu_memory",
    "--format=csv,noheader,nounits",
)


@dataclass(frozen=True, slots=True)
class ComputeProcess:
    gpu_uuid: str
    pid: int
    start_ticks: int | None
    used_bytes: int | None


@dataclass(frozen=True, slots=True)
class ProcessObservation:
    boot_id: str | None
    hardware_observed_at_ns: int
    observed_at_ns: int
    scope: Literal["nvidia_compute_only"]
    processes: tuple[ComputeProcess, ...]
    issues: tuple[str, ...]
    authorizes_execution: Literal[False] = False


def parse_compute_csv(raw: str) -> tuple[tuple[str, int, int | None], ...]:
    """Strictly parse query-compute-apps; MiB, not bytes or total GPU VRAM."""
    if not isinstance(raw, str) or len(raw) > _MAX_OUTPUT:
        raise ValueError("invalid compute output size")
    rows = [line.strip() for line in raw.splitlines() if line.strip()]
    if len(rows) > _MAX_PROCESSES:
        raise ValueError("too many compute rows")
    unique: set[tuple[str, int]] = set()
    result: list[tuple[str, int, int | None]] = []
    for row in rows:
        parts = [piece.strip() for piece in row.split(",")]
        if len(parts) != 3:
            raise ValueError("invalid compute row")
        uuid, pid_str, usage = parts
        if not _UUID.fullmatch(uuid):
            raise ValueError("invalid process GPU UUID")
        if not pid_str.isascii() or not pid_str.isdecimal():
            raise ValueError("invalid process PID")
        pid = int(pid_str)
        if pid <= 1:
            raise ValueError("unsupported process PID")
        if usage in {"N/A", "[Not Supported]"}:
            used_bytes: int | None = None
        elif usage.isascii() and usage.isdecimal():
            used_bytes = int(usage) * 1024 * 1024
            if used_bytes > (1 << 60):
                raise ValueError("invalid compute memory")
        else:
            raise ValueError("invalid compute usage")
        key = (uuid, pid)
        if key in unique:
            raise ValueError("ambiguous repeated GPU/PID")
        unique.add(key)
        result.append((uuid, pid, used_bytes))
    return tuple(sorted(result))


def parse_proc_start_ticks(stat: str, pid: int) -> int:
    """Read Linux /proc/PID/stat field 22, binding PID against reuse.

    The parenthesized comm field may contain closing parentheses. Splitting
    from the right avoids shifting the start-time field for such names.
    """
    if type(pid) is not int or pid <= 1:
        raise ValueError("invalid process identity")
    if not isinstance(stat, str) or len(stat) > 16 * 1024:
        raise ValueError("invalid proc stat size")
    prefix, sep, tail = stat.partition("(")
    if not sep or prefix.strip() != str(pid) or ")" not in tail:
        raise ValueError("invalid proc stat PID")
    after = tail.rsplit(")", 1)[1].split()
    if len(after) < 20:
        raise ValueError("truncated proc stat")
    value = after[19]
    if not value.isascii() or not value.isdecimal() or int(value) <= 0:
        raise ValueError("invalid process start ticks")
    return int(value)


def _read_process_stat(pid: int) -> str:
    # PID is parsed as a positive integer, never client-supplied path text.
    with (Path("/proc") / str(pid) / "stat").open("rb") as stream:
        raw = stream.read(16 * 1024 + 1)
    if len(raw) > 16 * 1024:
        raise ValueError("oversized /proc stat")
    return raw.decode("utf-8", errors="replace")


def _query_nvidia_processes() -> str:
    result = subprocess.run(
        _QUERY,
        capture_output=True,
        text=True,
        timeout=3,
        check=False,
        env={"LC_ALL": "C", "PATH": "/usr/bin:/bin"},
    )
    if result.returncode:
        raise OSError("NVIDIA compute query failed")
    return result.stdout


def collect_compute_processes(
    hardware: HardwareReading,
    *,
    query: Callable[[], str] = _query_nvidia_processes,
    read_stat: Callable[[int], str] = _read_process_stat,
    now_ns: Callable[[], int] = time.monotonic_ns,
) -> ProcessObservation:
    """Read NVIDIA compute rows and PID birth ticks once, explicitly.

    A missing process stat remains a row with unknown identity, not a vanished
    process. No process is signalled, killed, attached or granted a resource.
    """
    if not isinstance(hardware, HardwareReading):
        raise TypeError("hardware observation required")

    issues: set[str] = {"partial_compute_process_inventory"}
    if any(d.vendor == "amd" for d in hardware.devices):
        issues.add("amd_process_ownership_unavailable")
    if hardware.boot_id is None:
        issues.add("process_boot_epoch_missing")

    known_uuids = {
        d.identity
        for d in hardware.devices
        if d.vendor == "nvidia" and d.identity_source == "driver_uuid"
    }
    try:
        raw_rows = parse_compute_csv(query())
    except (OSError, UnicodeError, ValueError, subprocess.TimeoutExpired):
        issues.add("nvidia_compute_query_unavailable")
        raw_rows = ()

    processes: list[ComputeProcess] = []
    for uuid, pid, usage in raw_rows:
        if uuid not in known_uuids:
            issues.add("compute_gpu_uuid_not_in_hardware")
            continue
        start_ticks: int | None = None
        if hardware.boot_id is not None:
            try:
                start_ticks = parse_proc_start_ticks(read_stat(pid), pid)
            except (OSError, UnicodeError, ValueError):
                issues.add("process_birth_identity_unavailable")
        processes.append(
            ComputeProcess(
                gpu_uuid=uuid,
                pid=pid,
                start_ticks=start_ticks,
                used_bytes=usage,
            )
        )
    return ProcessObservation(
        boot_id=hardware.boot_id,
        hardware_observed_at_ns=hardware.observed_at_ns,
        observed_at_ns=now_ns(),
        scope="nvidia_compute_only",
        processes=tuple(sorted(processes, key=lambda p: (p.gpu_uuid, p.pid))),
        issues=tuple(sorted(issues)),
    )
