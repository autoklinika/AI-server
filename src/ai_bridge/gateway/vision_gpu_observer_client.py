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
