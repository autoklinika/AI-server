#!/usr/bin/env python3
"""Read-only privileged cross-UID GPU-FD observer for AI Platform Vision.

Runs from an immutable root-owned installation, never from a writable repo.
Accepts only authenticated AF_UNIX peers and fixed snapshot requests.
No shell, shell escape, device ioctl, writes to GPU, or arbitrary path APIs.
"""
from __future__ import annotations

import errno
import json
import os
from pathlib import Path
import pwd
import re
import secrets
import socket
import stat
import struct
import sys

SOCKET_PATH = Path("/run/ai-vision-gpu-observer/observer.sock")
GPU_PATHS = (Path("/dev/kfd"),)
RENDER_PATH = Path("/dev/dri")
PEER_ACCOUNTS = ("ai-gateway-rm", "ai-vision")
MAX_REQUEST = 512
MAX_REPLY = 262144


def pid_birth(stat_path: Path) -> int | None:
    try:
        raw=stat_path.read_text(encoding="ascii")
        fields=raw.rsplit(")", 1)[1].strip().split()
        value=int(fields[19])
        return value if value > 0 else None
    except (OSError, IndexError, ValueError):
        return None


def snapshot_gpu_clients(*, proc_root: Path = Path("/proc"),
                         gpu_paths: tuple[Path, ...] | None = None
                         ) -> tuple[tuple[int,int], ...] | None:
    """Inventory all kernel GPU-FD owners; None means incomplete visibility."""
    if gpu_paths is None:
        try:
            gpu_paths = GPU_PATHS + tuple(sorted(RENDER_PATH.glob("renderD*")))
        except OSError:
            return None
    if len(gpu_paths) < 2:  # /dev/kfd and at least one renderD
        return None
    devices=set()
    try:
        for path in gpu_paths:
            info=path.stat()
            if not stat.S_ISCHR(info.st_mode):
                return None
            devices.add(info.st_rdev)
        processes=[p for p in proc_root.iterdir() if p.name.isdecimal()]
    except OSError:
        return None

    found=[]
    for proc in processes:
        pid=int(proc.name)
        before=pid_birth(proc/"stat")
        if before is None:
            if proc.exists():
                return None  # unreadable live process, incomplete evidence
            continue
        try:
            fds=list((proc/"fd").iterdir())
        except FileNotFoundError:
            if proc.exists():
                return None
            continue
        except OSError:
            return None  # never treat cross-UID EPERM as empty
        owner=False
        for fd in fds:
            try:
                info=fd.stat()
                if stat.S_ISCHR(info.st_mode) and info.st_rdev in devices:
                    owner=True
            except FileNotFoundError:
                continue  # FD closed while sampling
            except OSError:
                return None
        after=pid_birth(proc/"stat")
        if after is None:
            if proc.exists():
                return None
            continue
        if before!=after:
            return None  # PID reuse during observation
        if owner:
            found.append((pid,before))
    return tuple(sorted(found))


def inspect_worker_executable(pid: int, birth: int, *, worker_uid: int) -> dict | None:
    """Single cross-UID /proc/exe attestation. No generic file/path API.

    The caller gives PID + birth as a freshness assertion, never an expected
    path to open. Root reads ONLY kernel /proc/<pid>/exe and returns its
    executable identity for a process owned by the fixed ai-vision UID.
    """
    if (type(pid) is not int or type(birth) is not int or pid<=1 or birth<=0
            or type(worker_uid) is not int or worker_uid<=0):
        return None
    proc=Path(f"/proc/{pid}")
    try:
        if proc.stat().st_uid!=worker_uid:
            return None
        before=pid_birth(proc/"stat")
        if before!=birth:
            return None
        raw=os.readlink(proc/"exe")
        if not raw.startswith("/") or raw.endswith(" (deleted)") or len(raw)>4096:
            return None
        executable=Path(raw).resolve(strict=True)
        info=(proc/"exe").stat()
        if not stat.S_ISREG(info.st_mode):
            return None
        disk=executable.stat()
        if (disk.st_dev,disk.st_ino)!=(info.st_dev,info.st_ino):
            return None
        if proc.stat().st_uid!=worker_uid or pid_birth(proc/"stat")!=birth:
            return None
        return {"pid":pid,"birth":birth,"uid":worker_uid,"exe":str(executable)}
    except (OSError,ValueError,RuntimeError):
        return None


def allowed_uids() -> frozenset[int]:
    result=set()
    for account in PEER_ACCOUNTS:
        result.add(pwd.getpwnam(account).pw_uid)
    if len(result)!=len(PEER_ACCOUNTS) or 0 in result:
        raise RuntimeError("trusted observer accounts unavailable")
    return frozenset(result)


# SOURCE-ONLY protocol scaffolding. No positive collector or execution API.
# Regenerated on every observer process start; no history survives restart.
TERMINAL_EPOCH = secrets.token_hex(16)


def strict_request(payload: bytes) -> dict | None:
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate field")
            result[key] = value
        return result
    try:
        if not payload or len(payload) > MAX_REQUEST:
            return None
        request = json.loads(payload, object_pairs_hook=unique)
        if (type(request) is not dict or type(request.get("version")) is not int
                or request["version"] != 1):
            return None
        return request
    except (ValueError, UnicodeError, TypeError, RecursionError):
        return None


def terminal_request(request: dict, *, peer_uid: int) -> dict:
    """Reserved, tokenless ABI: deny admission until containment is implemented.

    There is deliberately no event injection, signature/boolean evidence,
    handle allocation, or configurable backend that could manufacture success.
    No /proc, bus, cgroup or GPU reads are needed to establish this denial.
    UID 993 is the controller; runner and model remain UID 994. Numeric UIDs
    must be checked against account provisioning before any future deployment.
    """
    if peer_uid != 993:
        return {"schema_version": 1, "status": "denied"}
    invalid = {"schema_version": 1, "status": "invalid_request"}
    if request["op"] == "register_scope":
        if set(request) != {"version", "op", "runner_pid", "runner_birth",
                            "pid", "birth", "scope_suffix"}:
            return invalid
        for key in ("runner_pid", "runner_birth", "pid", "birth"):
            value = request[key]
            if type(value) is not int or not 1 < value < 2**63:
                return invalid
        suffix = request["scope_suffix"]
        if type(suffix) is not str or re.fullmatch(r"[0-9a-f]{12}", suffix) is None:
            return invalid
        reason = "containment_unavailable"
    else:
        if set(request) != {"version", "op", "handle", "epoch"}:
            return invalid
        for key in ("handle", "epoch"):
            if (type(request[key]) is not str
                    or re.fullmatch(r"[0-9a-f]{32}", request[key]) is None):
                return invalid
        reason = "unregistered" if request["epoch"] == TERMINAL_EPOCH else "epoch_mismatch"
    return {"schema_version": 1, "status": "unknown", "reason": reason,
            "epoch": TERMINAL_EPOCH}


def dispatch(payload: bytes, *, peer_uid: int, trusted_uids: frozenset[int],
             controller_uid: int | None = None, worker_uid: int | None = None) -> bytes:
    if peer_uid not in trusted_uids:
        result={"schema_version":1,"status":"denied"}
    else:
        request = strict_request(payload)
        if request is not None and request.get("op") in ("register_scope", "query_terminal"):
            result = terminal_request(request, peer_uid=peer_uid)
        elif request=={"op":"snapshot","version":1}:
            clients=snapshot_gpu_clients()
            result=({"schema_version":1,"status":"ok",
                     "gpu_clients":[{"pid":pid,"birth":birth} for pid,birth in clients]}
                    if clients is not None else
                    {"schema_version":1,"status":"evidence_unavailable"})
        elif (type(request) is dict and set(request)=={"op","version","pid","birth"}
              and request.get("op")=="inspect_worker" and request.get("version")==1
              and type(request.get("pid")) is int and type(request.get("birth")) is int):
            # Unlike GPU inventory, privileged cross-UID executable evidence is
            # for the CONTROL account only, never for ai-vision or arbitrary UIDs.
            if controller_uid is None:
                try:controller_uid=pwd.getpwnam("ai-gateway-rm").pw_uid
                except KeyError:controller_uid=-1
            if worker_uid is None:
                try:worker_uid=pwd.getpwnam("ai-vision").pw_uid
                except KeyError:worker_uid=-1
            if peer_uid!=controller_uid:
                result={"schema_version":1,"status":"denied"}
            else:
                identity=inspect_worker_executable(request["pid"],request["birth"],
                                                  worker_uid=worker_uid)
                result=({"schema_version":1,"status":"ok","worker":identity}
                        if identity is not None else
                        {"schema_version":1,"status":"evidence_unavailable"})
        else:
            result={"schema_version":1,"status":"invalid_request"}
    encoded=(json.dumps(result,sort_keys=True,separators=(",",":"))+"\n").encode("ascii")
    if len(encoded)>MAX_REPLY:
        return b'{"schema_version":1,"status":"evidence_unavailable"}\n'
    return encoded


def serve() -> None:
    trusted_uids=allowed_uids()
    location=SOCKET_PATH
    if not location.parent.is_dir():
        raise RuntimeError("systemd RuntimeDirectory not available")
    if location.exists():
        raise RuntimeError("socket already exists; refuse unlink of foreign path")
    os.umask(0o007)
    with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as listener:
        listener.bind(str(location))
        os.chmod(location,0o660)
        listener.listen(16)
        listener.settimeout(2.0)
        while True:
            try:
                conn,_=listener.accept()
            except socket.timeout:
                continue
            with conn:
                conn.settimeout(3.0)
                try:
                    _pid,uid,_gid=struct.unpack("3i",conn.getsockopt(
                        socket.SOL_SOCKET,socket.SO_PEERCRED,struct.calcsize("3i")))
                    raw=conn.recv(MAX_REQUEST+1)
                    if len(raw)>MAX_REQUEST or not raw:
                        answer=b'{"schema_version":1,"status":"invalid_request"}\n'
                    else:
                        answer=dispatch(raw,peer_uid=uid,trusted_uids=trusted_uids)
                    conn.sendall(answer)
                except (OSError,struct.error):
                    continue


if __name__=="__main__":
    serve()
