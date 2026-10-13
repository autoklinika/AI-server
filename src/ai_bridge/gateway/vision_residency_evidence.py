"""Read-only Linux evidence for a single-owner Vision GPU worker.

No direct GPU actions; evidence is used by shared GPUResidency before
reopening Ollama's pool. An absent/ambiguous observation fails closed.
"""
from __future__ import annotations

from pathlib import Path


def worker_birth_ticks(pid: int) -> int | None:
    """Kernel /proc PID starttime (field 22), immune to PID reuse across a run."""
    if type(pid) is not int or pid <= 1:
        return None
    try:
        stat = Path(f"/proc/{pid}/stat").read_text(encoding="ascii")
        # Field 2 (comm) may contain spaces or parentheses; split AFTER last ')'.
        remainder = stat.rsplit(")", 1)[1].strip().split()
        return int(remainder[19]) if int(remainder[19]) > 0 else None
    except FileNotFoundError:
        return None  # Process conclusively exited.
    except (OSError, IndexError, ValueError):
        return -1  # Unknown identity is NOT proof of process exit.


def gpu_vram_used_bytes() -> int | None:
    """Single local AMD GPU memory reading; fail closed when ambiguous."""
    entries = sorted(Path("/sys/class/drm").glob("card*/device/mem_info_vram_used"))
    if len(entries) != 1:
        return None
    try:
        raw = entries[0].read_text(encoding="ascii").strip()
        amount = int(raw)
        return amount if amount >= 0 else None
    except (OSError, ValueError):
        return None
