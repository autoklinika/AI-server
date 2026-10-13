"""DEV: isolated Vision control-plane broker, never part of a model process.

Runs as ai-gateway-rm. A root-owned runner service under ai-vision asks for a
FIXED background Vision lease over AF_UNIX. Gateway bearer never crosses IPC.
All modifications remain private to the existing shared Resource Manager.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import os
from pathlib import Path
import pwd
import secrets
import socket
import stat
import struct
import threading
import time
from typing import Callable

from ai_bridge.benchmarks.vision_rm_executor import VisionExecutionError, call
from ai_bridge.gateway.vision_residency_evidence import worker_birth_ticks, worker_cgroup_path

SOCKET_PATH = Path("/run/ai-vision-rm-broker/control.sock")
RUNNER_UNIT = "ai-vision-rm-runner.service"
MAX_REQUEST = 4096


def trusted_runner_pid(pid: int, *, uid: int, runner_path: Path, sha256_hex: str) -> bool:
    """Peer must be an unmodified binary in the exact protected systemd unit."""
    if type(pid) is not int or pid <= 1 or not runner_path.is_absolute():
        return False
    try:
        proc=Path(f"/proc/{pid}")
        if proc.stat().st_uid != uid:
            return False
        groups=(proc/"cgroup").read_text().splitlines()
        if groups != [f"0::/system.slice/{RUNNER_UNIT}"]:
            return False
        argv=[a.decode("utf-8") for a in (proc/"cmdline").read_bytes().rstrip(b"\x00").split(b"\x00")]
        # Pin the exact root-owned service ExecStart command line. Python -I
        # occurs BEFORE the script and must never be mistaken for a path.
        if (len(argv)!=3 or argv[1]!="-I" or
                Path(argv[2]).resolve(strict=True)!=runner_path):
            return False
        actual=runner_path.stat()
        if actual.st_uid!=0 or actual.st_mode & 0o022 or not stat.S_ISREG(actual.st_mode):
            return False
        return sha256(runner_path.read_bytes()).hexdigest()==sha256_hex
    except (OSError,UnicodeError,ValueError):
        return False


@dataclass
class Session:
    nonce: str
    owner_pid: int
    owner_birth: int
    lease_id: str
    use_id: str | None = None
    use_token: str | None = None
    admission_uncertain: bool = False


class ControlBroker:
    def __init__(self, *, gateway: str, vision_uid: int,
                 runner_path: Path, runner_sha256: str,
                 api_call: Callable = call,
                 peer_validator: Callable | None = None) -> None:
        self.gateway=gateway
        self.vision_uid=vision_uid
        self.runner_path=runner_path
        self.runner_sha256=runner_sha256
        self.api_call=api_call
        self.peer_validator=peer_validator
        self.session: Session | None = None
        self.reservation_uncertain = False
        self._lock=threading.RLock()

    def _peer_allowed(self, pid: int, uid: int) -> bool:
        if uid!=self.vision_uid:
            return False
        if self.peer_validator is not None:
            return bool(self.peer_validator(pid,uid))
        return trusted_runner_pid(pid,uid=uid,runner_path=self.runner_path,sha256_hex=self.runner_sha256)

    def request(self, command: dict, *, peer_pid: int, peer_uid: int) -> dict:
        if not isinstance(command,dict) or type(command.get("op")) is not str:
            return {"status":"denied"}
        if not self._peer_allowed(peer_pid,peer_uid):
            return {"status":"denied"}
        with self._lock:
            op=command["op"]
            if op=="create" and set(command)=={"op"}:
                if self.session is not None or self.reservation_uncertain:
                    return {"status":"busy"}
                birth=worker_birth_ticks(peer_pid)
                if birth is None or birth<=0:
                    return {"status":"identity_unavailable"}
                # A lost POST reply may have created a lease. Never retry create
                # in this process or claim cleanup of an unidentified lease.
                self.reservation_uncertain = True
                lease=self.api_call(self.gateway,"POST","/resource/leases",{
                    "source":"vision-broker","workload":"vision-benchmark",
                    "priority_class":"background"})
                if (type(lease) is not dict or type(lease.get("lease_id")) is not str
                        or not lease["lease_id"] or lease.get("state") not in
                        ("queued", "active")):
                    return {"status":"reservation_unverified"}
                sid=secrets.token_urlsafe(24)
                self.session=Session(sid,peer_pid,birth,lease["lease_id"])
                self.reservation_uncertain = False
                return {"status":"ok","session":sid,"state":lease["state"]}
            sess=self.session
            if (sess is None or command.get("session")!=sess.nonce or
                peer_pid!=sess.owner_pid or worker_birth_ticks(peer_pid)!=sess.owner_birth):
                return {"status":"denied"}
            if op=="poll" and set(command)=={"op","session"}:
                state=self.api_call(self.gateway,"GET",f"/resource/leases/{sess.lease_id}")
                return {"status":"ok","state":state["state"]}
            if op=="begin" and set(command)=={"op","session","worker_pid","scope_path"}:
                if sess.use_id is not None or sess.admission_uncertain:
                    return {"status":"already_started"}
                worker=command["worker_pid"]
                scope=command["scope_path"]
                if (type(worker) is not int or worker<=1 or not isinstance(scope,str) or
                    worker_cgroup_path(worker,expected_uid=self.vision_uid)!=scope or Path(f"/proc/{worker}").stat().st_uid!=self.vision_uid):
                    return {"status":"worker_scope_denied"}
                # A lost/malformed admission reply may already own GPU resources.
                sess.admission_uncertain=True
                use=self.api_call(self.gateway,"POST",f"/resource/leases/{sess.lease_id}/uses",{
                    "provider":"vision-local","capability":"image-analysis",
                    "worker_pid":worker,"scope_path":scope})
                if (not isinstance(use,dict) or type(use.get("use_id")) is not str
                        or not use["use_id"] or type(use.get("worker_token")) is not str
                        or len(use["worker_token"])<32):
                    return {"status":"scope_token_unavailable"}
                sess.use_id=use["use_id"]
                sess.use_token=use["worker_token"]
                sess.admission_uncertain=False
                return {"status":"ok","authorization":{"lease_id":sess.lease_id,
                                    "use_id":sess.use_id,"worker_token":sess.use_token}}
            if op=="finish" and set(command)=={"op","session"}:
                if sess.admission_uncertain:
                    return {"status":"cleanup_failed", "stage":"use_cleanup",
                            "reason":"admission_outcome_unknown"}
                if sess.use_id is not None:
                    failure=self._finish_delete(
                        f"/resource/leases/{sess.lease_id}/uses/{sess.use_id}", "use_cleanup")
                    if failure is not None:
                        return failure
                failure=self._finish_delete(f"/resource/leases/{sess.lease_id}", "lease_release")
                if failure is not None:
                    return failure
                self.session=None
                return {"status":"released"}
            return {"status":"denied"}

    def _finish_delete(self, path: str, stage: str) -> dict | None:
        # Never serialize exception text, URLs, response bodies or credentials.
        from urllib.error import HTTPError, URLError
        try:
            result=self.api_call(self.gateway,"DELETE",path)
        except HTTPError as exc:
            reason="unauthorized" if exc.code in (401,403) else "http_error"
            failure={"status":"cleanup_failed", "stage":stage, "reason":reason}
            if type(exc.code) is int and 100 <= exc.code <= 599:
                failure["http_status"]=exc.code
            exc.close()
            return failure
        except (TimeoutError, URLError, OSError):
            return {"status":"cleanup_failed", "stage":stage, "reason":"transport_error"}
        except Exception:
            return {"status":"cleanup_failed", "stage":stage, "reason":"gateway_error"}
        if type(result) is not dict or set(result)!={"released"} or result["released"] is not True:
            return {"status":"cleanup_failed", "stage":stage, "reason":"release_unverified"}
        return None

    def heartbeat_loop(self, stop: threading.Event):
        while not stop.wait(5):
            with self._lock:
                sess=self.session
                if sess is None:continue
                # A dead supervisor cannot be assumed to have cleaned GPU.
                # The external GPU use stays pinned; operator recovery required.
                if worker_birth_ticks(sess.owner_pid)!=sess.owner_birth:
                    continue
                try:
                    self.api_call(self.gateway,"POST",f"/resource/leases/{sess.lease_id}/heartbeat")
                except Exception:
                    pass  # Fail closed: no forged release or admission.


def serve(broker: ControlBroker, *, socket_path: Path=SOCKET_PATH,
          stop_event: threading.Event | None = None) -> None:
    socket_path.parent.mkdir(parents=True,exist_ok=True)
    if socket_path.exists():
        raise RuntimeError("existing broker socket: refuse to unlink")
    stop=stop_event or threading.Event()
    t=threading.Thread(target=broker.heartbeat_loop,args=(stop,),daemon=True)
    os.umask(0o007)
    with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as listener:
        listener.bind(str(socket_path))
        os.chmod(socket_path,0o660)
        listener.listen(8)
        listener.settimeout(2)
        t.start()
        try:
            while not stop.is_set():
                try:connection,_=listener.accept()
                except socket.timeout:continue
                with connection:
                    connection.settimeout(8)
                    try:
                        pid,uid,_=struct.unpack("3i",connection.getsockopt(
                            socket.SOL_SOCKET,socket.SO_PEERCRED,struct.calcsize("3i")))
                        request=connection.recv(MAX_REQUEST+1)
                        if len(request)>MAX_REQUEST or not request:
                            response={"status":"invalid"}
                        else:
                            response=broker.request(json.loads(request),peer_pid=pid,peer_uid=uid)
                        # Scope token is only returned for a successful begin,
                        # never persisted to logs or command-line arguments.
                        connection.sendall((json.dumps(response,separators=(",",":"))+"\n").encode())
                    except (OSError,ValueError,KeyError,VisionExecutionError):
                        connection.sendall(b'{"status":"gateway_error"}\n')
        finally:
            stop.set()
            t.join(timeout=3)


def main() -> None:
    uid=os.getuid()
    if uid!=pwd.getpwnam("ai-gateway-rm").pw_uid:
        raise SystemExit("Vision RM broker must run as ai-gateway-rm")
    if "VISION_RM_EXECUTOR_TOKEN" in os.environ:
        raise SystemExit("control bearer may only be provisioned from protected file")
    if os.environ.get("VISION_RM_EXECUTOR_TOKEN_FILE") != "/etc/ai-platform/vision-rm/executor.token":
        raise SystemExit("missing root-controlled service credential location")
    runner=Path("/usr/local/libexec/ai-platform/vision-rm-runner.py")
    info=runner.stat()
    if info.st_uid!=0 or info.st_mode & 0o022:
        raise SystemExit("runner is not immutable root-owned code")
    broker=ControlBroker(
        gateway=os.environ.get("VISION_RM_GATEWAY_URL", "http://127.0.0.1:11575"),
        vision_uid=pwd.getpwnam("ai-vision").pw_uid,
        runner_path=runner,runner_sha256=sha256(runner.read_bytes()).hexdigest())
    serve(broker)


if __name__=="__main__":
    main()
