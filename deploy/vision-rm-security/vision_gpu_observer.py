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


def allowed_uids() -> frozenset[int]:
    result=set()
    for account in PEER_ACCOUNTS:
        result.add(pwd.getpwnam(account).pw_uid)
    if len(result)!=len(PEER_ACCOUNTS) or 0 in result:
        raise RuntimeError("trusted observer accounts unavailable")
    return frozenset(result)


def dispatch(payload: bytes, *, peer_uid: int, trusted_uids: frozenset[int]) -> bytes:
    if peer_uid not in trusted_uids:
        result={"schema_version":1,"status":"denied"}
    else:
        try:
            request=json.loads(payload)
        except (ValueError,UnicodeError):
            request=None
        if request!={"op":"snapshot","version":1}:
            result={"schema_version":1,"status":"invalid_request"}
        else:
            clients=snapshot_gpu_clients()
            result=({"schema_version":1,"status":"ok",
                     "gpu_clients":[{"pid":pid,"birth":birth} for pid,birth in clients]}
                    if clients is not None else
                    {"schema_version":1,"status":"evidence_unavailable"})
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
