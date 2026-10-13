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

def worker_cgroup_path(pid: int, *, expected_uid: int | None = None) -> str | None:
    """Return exact, trusted user-manager Vision scope for the worker PID."""
    import os
    import re
    try:
        uid = Path(f"/proc/{pid}").stat().st_uid
        if uid != (expected_uid if expected_uid is not None else os.getuid()):
            return None  # Only the configured model worker UID is admissible.
        raw = Path(f"/proc/{pid}/cgroup").read_text(encoding="ascii")
        lines = [line[3:].strip() for line in raw.splitlines() if line.startswith("0::")]
        if len(lines) != 1:
            return None
        path = lines[0]
        prefix = f"/user.slice/user-{uid}.slice/user@{uid}.service/app.slice/"
        if not path.startswith(prefix):
            return None
        scope = path[len(prefix):]
        if not re.fullmatch(r"vision-bench-[0-9a-f]{12}\.scope", scope):
            return None
        return path
    except (OSError, ValueError):
        return None


def scoped_processes(scope_path: str) -> set[int] | None:
    """Kernel cgroup.procs evidence; unknown state returns None, not empty."""
    from pathlib import PurePosixPath
    import re
    if not isinstance(scope_path, str) or not scope_path.startswith("/user.slice/"):
        return None
    scope = PurePosixPath(scope_path)
    if ".." in scope.parts or not re.fullmatch(r"vision-bench-[0-9a-f]{12}\.scope", scope.name):
        return None
    path = Path("/sys/fs/cgroup") / scope_path.lstrip("/") / "cgroup.procs"
    try:
        return {int(pid) for pid in path.read_text(encoding="ascii").split()}
    except (FileNotFoundError, OSError, ValueError):
        return None  # Missing scope alone is never proof of successful exit.


def scope_members_or_terminal(scope_path: str) -> set[int] | None:
    """Require empty-or-absent cgroup AND attested terminal systemd state.

    Unknown/unreadable systemd status or a collected unit is not proof.
    """
    import os
    import subprocess
    from pathlib import PurePosixPath
    members=scoped_processes(scope_path)
    if members:
        return members  # A nonempty cgroup definitively blocks cleanup.
    # An empty cgroup (or a vanished cgroup) is not sufficient proof that the
    # transient systemd scope terminated. Require independently attested
    # terminal state in BOTH cases before returning an empty set.
    if not isinstance(scope_path,str):
        return None
    unit=PurePosixPath(scope_path).name
    if not __import__('re').fullmatch(r"vision-bench-[0-9a-f]{12}\.scope",unit):
        return None
    uid=os.getuid()
    expected=f"/user.slice/user-{uid}.slice/user@{uid}.service/app.slice/{unit}"
    if scope_path!=expected:
        return None
    env={**os.environ,"XDG_RUNTIME_DIR":f"/run/user/{uid}",
         "DBUS_SESSION_BUS_ADDRESS":f"unix:path=/run/user/{uid}/bus"}
    try:
        proc=subprocess.run(["systemctl","--user","show",unit,
                             "-p","LoadState","-p","ActiveState",
                             "-p","SubState","-p","ControlGroup"],
                             env=env,text=True,capture_output=True,timeout=3,check=False)
        if proc.returncode!=0:
            return None
        fields={}
        for item in proc.stdout.splitlines():
            if "=" not in item:
                return None
            key,value=item.split("=",1)
            if key in fields or key not in {"LoadState","ActiveState","SubState","ControlGroup"}:
                return None
            fields[key]=value
        # A nonexistent scope exits 0 and reports not-found + inactive +
        # empty ControlGroup. That is NOT terminal proof.
        # A garbage-collected scope is therefore unknown, not clean.
        if (fields.get("LoadState")!="loaded"
                or fields.get("ActiveState")!="inactive"
                or fields.get("SubState")!="dead"
                or fields.get("ControlGroup")!=""):
            return None
        return set()
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None


def gpu_device_openers() -> frozenset[tuple[int,int]] | None:
    """Inventory of live kernel GPU FD holders across all UIDs.

    This probe needs authority to inspect /proc/*/fd for ALL local users.
    Do not substitute empty results for EPERM: that would misreport GPU
    cleanup when Ollama/ComfyUI are owned by different service accounts.
    """
    import os
    from stat import S_ISCHR
    gpu_devices=[]
    for path in (Path("/dev/kfd"),*Path("/dev/dri").glob("renderD*")):
        try:
            entry=path.stat()
            if not S_ISCHR(entry.st_mode):
                return None
            gpu_devices.append(entry.st_rdev)
        except OSError:
            return None
    if not gpu_devices:
        return None
    device_ids=frozenset(gpu_devices)
    opened=set()
    try:
        processes=[path for path in Path("/proc").iterdir() if path.name.isdecimal()]
    except OSError:
        return None
    for proc in processes:
        pid=int(proc.name)
        try:
            fds=list((proc/"fd").iterdir())
        except FileNotFoundError:
            continue  # PID exited between enumeration steps.
        except (OSError,PermissionError):
            return None  # Missing cross-UID FD visibility: fail closed.
        holds_gpu=False
        for fd in fds:
            try:
                stat=fd.stat()
                if S_ISCHR(stat.st_mode) and stat.st_rdev in device_ids:
                    holds_gpu=True
                    break
            except FileNotFoundError:
                continue  # FD closed during sample.
            except (OSError,PermissionError):
                return None
        if holds_gpu:
            birth=worker_birth_ticks(pid)
            if birth is None:  # PID exited; no live identity to record.
                continue
            if birth<=0:
                return None
            opened.add((pid,birth))
    return frozenset(opened)
