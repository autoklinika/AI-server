"""Unprivileged, read-only client for a root-owned GPU-FD observer socket.

Every observation is fail-closed. No arbitrary commands, subprocesses or GPU
writes; a hostile/missing server is never equivalent to zero GPU clients.
"""
from __future__ import annotations

import json
from pathlib import Path
import socket
import struct


def snapshot_observer(*, socket_path: Path, expected_uid: int = 0
                      ) -> frozenset[tuple[int,int]] | None:
    if not socket_path.is_absolute() or not socket_path.name.endswith(".sock"):
        return None
    try:
        with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as connection:
            connection.settimeout(3.0)
            connection.connect(str(socket_path))
            _,uid,_=struct.unpack("3i",connection.getsockopt(
                socket.SOL_SOCKET,socket.SO_PEERCRED,struct.calcsize("3i")))
            if uid!=expected_uid:
                return None
            connection.sendall(b'{"op":"snapshot","version":1}\n')
            payload=bytearray()
            while len(payload)<=262144:
                fragment=connection.recv(min(8192,262145-len(payload)))
                if not fragment:
                    break
                payload.extend(fragment)
                if b"\n" in fragment:
                    break
            if len(payload)>262144 or payload.count(b"\n")!=1:
                return None
        answer=json.loads(payload)
        if (type(answer) is not dict or answer.get("schema_version")!=1
                or answer.get("status")!="ok" or
                set(answer)!={"schema_version","status","gpu_clients"}):
            return None
        clients=answer["gpu_clients"]
        if type(clients) is not list or len(clients)>32768:
            return None
        identities=set()
        for client in clients:
            if (type(client) is not dict or set(client)!={"pid","birth"}
                or type(client["pid"]) is not int or type(client["birth"]) is not int
                or client["pid"]<=1 or client["birth"]<=0):
                return None
            identities.add((client["pid"],client["birth"]))
        if len(identities)!=len(clients):
            return None
        return frozenset(identities)
    except (OSError,ValueError,UnicodeError,struct.error,TypeError):
        return None


def inspect_worker_observer(*, socket_path: Path, pid: int, birth: int,
                            worker_uid: int, expected_uid: int = 0) -> Path | None:
    """Ask trusted ROOT observer for precisely one ai-vision process exe.

    Never expose generic privileged paths, arbitrary commands or a token.
    Unknown, wrong peer UID, stale PID, malformed response => fail closed.
    """
    if (type(pid) is not int or pid<=1 or type(birth) is not int or birth<=0
            or type(worker_uid) is not int or worker_uid<=0 or
            not socket_path.is_absolute() or not socket_path.name.endswith(".sock")):
        return None
    try:
        with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as connection:
            connection.settimeout(3.0)
            connection.connect(str(socket_path))
            _,uid,_=struct.unpack("3i",connection.getsockopt(
                socket.SOL_SOCKET,socket.SO_PEERCRED,struct.calcsize("3i")))
            if uid!=expected_uid:
                return None
            connection.sendall(json.dumps({"op":"inspect_worker","version":1,
                                           "pid":pid,"birth":birth}).encode("ascii")+b"\n")
            payload=bytearray()
            while len(payload)<=8192:
                fragment=connection.recv(min(1024,8193-len(payload)))
                if not fragment:break
                payload.extend(fragment)
                if b"\n" in fragment:break
            if len(payload)>8192 or payload.count(b"\n")!=1:
                return None
        answer=json.loads(payload)
        if (type(answer) is not dict or set(answer)!={"schema_version","status","worker"}
                or answer["schema_version"]!=1 or answer["status"]!="ok"):
            return None
        worker=answer["worker"]
        if (type(worker) is not dict or set(worker)!={"pid","birth","uid","exe"}
                or worker["pid"]!=pid or worker["birth"]!=birth
                or worker["uid"]!=worker_uid or type(worker["exe"]) is not str
                or len(worker["exe"])>4096):
            return None
        exe=Path(worker["exe"])
        if not exe.is_absolute():return None
        return exe.resolve(strict=True)
    except (OSError,ValueError,UnicodeError,struct.error,TypeError):
        return None
