"""Root observer and unprivileged client: deterministic non-root security tests."""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import socket
import stat
import tempfile
import threading
import time

from ai_bridge.gateway.vision_gpu_observer_client import snapshot_observer

SOURCE = Path(__file__).resolve().parents[1] / "deploy/vision-rm-security/vision_gpu_observer.py"
SPEC = importlib.util.spec_from_file_location("vision_gpu_observer", SOURCE)
observer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(observer)


def test_unauthorized_peer_gets_no_gpu_inventory(monkeypatch):
    monkeypatch.setattr(observer, "snapshot_gpu_clients", lambda: ((101, 222),))
    data = observer.dispatch(b'{"op":"snapshot","version":1}', peer_uid=501,
                             trusted_uids=frozenset({994, 993}))
    assert b'"denied"' in data and b'"pid"' not in data


def test_trusted_peer_snapshot_is_schema_pinned(monkeypatch):
    monkeypatch.setattr(observer, "snapshot_gpu_clients", lambda: ((101, 222),))
    trusted = frozenset({994})
    data = observer.dispatch(b'{"op":"snapshot","version":1}', peer_uid=994, trusted_uids=trusted)
    assert b'"status":"ok"' in data and b'"pid":101' in data
    invalid = observer.dispatch(b'{"op":"run","command":"id"}', peer_uid=994, trusted_uids=trusted)
    assert b'"invalid_request"' in invalid


def test_unreadable_or_incomplete_inventory_is_not_empty(monkeypatch):
    monkeypatch.setattr(observer, "snapshot_gpu_clients", lambda: None)
    response = observer.dispatch(b'{"op":"snapshot","version":1}', peer_uid=994,
                                 trusted_uids=frozenset({994}))
    assert b'"evidence_unavailable"' in response and b'"status":"ok"' not in response


def test_synthetic_gpu_fd_holder_and_pid_birth():
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        proc = root / "4242"
        (proc / "fd").mkdir(parents=True)
        (proc / "fd" / "5").symlink_to("/dev/null")
        (proc / "stat").write_text(
            "4242 (worker with spaces) S " + " ".join(["0"] * 18 + ["123456"] + ["0"] * 10)
        )
        clients = observer.snapshot_gpu_clients(proc_root=root,
            gpu_paths=(Path("/dev/null"), Path("/dev/zero")))
        assert clients == ((4242, 123456),)


def test_socket_client_rejects_wrong_server_uid():
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "observer.sock"
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
            server.bind(str(path))
            server.listen(1)
            def handler():
                peer, _ = server.accept()
                with peer:
                    peer.recv(512)
            t = threading.Thread(target=handler, daemon=True)
            t.start()
            assert snapshot_observer(socket_path=path, expected_uid=os.getuid() + 1) is None
            # Connection was rejected locally; close server to finish bounded test.
            server.close()
            t.join(timeout=2)
