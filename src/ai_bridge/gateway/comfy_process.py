from __future__ import annotations

import asyncio
import os
from pathlib import Path
import signal
import subprocess

from .residency import ResidencyError


async def resume_stopped_managed_comfy(
    service: str = "comfyui.service",
    *,
    settle_timeout: float = 2.0,
) -> bool:
    """Resume only the exact systemd-managed ComfyUI process when SIGSTOPped.

    A stopped process is still reported by systemd as active/running, so HTTP
    health alone cannot distinguish it from a wedged worker. Identity is
    verified through systemd MainPID, uid and cgroup before pidfd SIGCONT.
    Traced processes are deliberately not resumed.
    """
    try:
        result = await asyncio.to_thread(
            subprocess.run,
            ["systemctl", "show", service, "-p", "MainPID", "--value"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=2,
            check=False,
        )
    except Exception as exc:
        raise ResidencyError("cannot inspect managed ComfyUI process") from exc
    if result.returncode != 0:
        raise ResidencyError("cannot inspect managed ComfyUI process")
    raw = result.stdout.strip()
    if not raw.isdigit() or int(raw) <= 1:
        raise ResidencyError("managed ComfyUI MainPID unavailable")
    pid = int(raw)
    proc = Path("/proc") / str(pid)
    try:
        if proc.stat().st_uid != os.getuid():
            raise ResidencyError("managed ComfyUI uid mismatch")
        cgroups = (proc / "cgroup").read_text().splitlines()
        expected = f"0::/system.slice/{service}"
        if expected not in cgroups:
            raise ResidencyError("managed ComfyUI cgroup mismatch")
        state = next(
            line.split()[1]
            for line in (proc / "status").read_text().splitlines()
            if line.startswith("State:")
        )
    except ResidencyError:
        raise
    except Exception as exc:
        raise ResidencyError("cannot verify managed ComfyUI identity") from exc

    if state == "t":
        raise ResidencyError("managed ComfyUI is ptrace-stopped")
    if state != "T":
        return False

    try:
        fd = os.pidfd_open(pid)
        try:
            signal.pidfd_send_signal(fd, signal.SIGCONT)
        finally:
            os.close(fd)
    except Exception as exc:
        raise ResidencyError("cannot resume managed ComfyUI") from exc

    loop = asyncio.get_running_loop()
    deadline = loop.time() + max(0.1, settle_timeout)
    while loop.time() < deadline:
        try:
            current = next(
                line.split()[1]
                for line in (proc / "status").read_text().splitlines()
                if line.startswith("State:")
            )
        except Exception as exc:
            raise ResidencyError("managed ComfyUI disappeared after SIGCONT") from exc
        if current != "T":
            return True
        await asyncio.sleep(0.05)
    raise ResidencyError("managed ComfyUI did not resume after SIGCONT")
