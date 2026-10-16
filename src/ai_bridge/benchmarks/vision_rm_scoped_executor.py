"""DEV-only cgroup v2 scoped Vision benchmark executor sharing AI Gateway RM.

Linux systemd user manager is required. No GPU work before Gateway's
provider-specific Vision use token. Any uncertain cleanup fails closed.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
import threading
import time

from .vision_rm_executor import VisionExecutionError, call
from ai_bridge.gateway.vision_residency_evidence import (
    scoped_processes,scope_members_or_terminal,worker_cgroup_path)


class ScopedVisionExecutor:
    def __init__(self, *, base: str = "http://127.0.0.1:11435"):
        if not base.startswith("http://127.0.0.1:") and not base.startswith("http://localhost:"):
            raise ValueError("Gateway must be loopback")
        self.base = base.rstrip("/")

    @staticmethod
    def _systemd_env() -> dict[str,str]:
        uid = os.getuid()
        path = f"/run/user/{uid}/bus"
        if not Path(path).is_socket():
            raise VisionExecutionError("systemd user bus unavailable")
        return {**os.environ,
                "XDG_RUNTIME_DIR":f"/run/user/{uid}",
                "DBUS_SESSION_BUS_ADDRESS":f"unix:path={path}"}

    @staticmethod
    def _scope_call(env: dict, *params: str) -> None:
        subprocess.run(["systemctl","--user",*params], env=env,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       timeout=7,check=False)

    def execute(self, *, python: Path, script: Path, args: list[str], log: Path,
                max_seconds: float = 110, queue_timeout_seconds: float = 120) -> dict:
        if max_seconds < 10 or queue_timeout_seconds < 1:
            raise ValueError("invalid timeouts")
        env = self._systemd_env()
        if log.exists():raise FileExistsError("refuse to overwrite log")
        log.parent.mkdir(parents=True,exist_ok=True)
        unit = "vision-bench-"+secrets.token_hex(6)
        uid = os.getuid()
        scope_path = f"/user.slice/user-{uid}.slice/user@{uid}.service/app.slice/{unit}.scope"
        lease_id = use_id = None
        stop = threading.Event()
        heartbeat_errors = []
        heart = None
        handle = None
        worker_pid = None
        started = time.monotonic()

        def heartbeat():
            while not stop.wait(5):
                if lease_id is not None:
                    try:
                        status=call(self.base,"POST",f"/resource/leases/{lease_id}/heartbeat")
                        if status.get("state") not in {"active","queued"}:
                            raise VisionExecutionError("lease is not active/queued")
                    except Exception as exc:
                        heartbeat_errors.append(type(exc).__name__)
                        stop.set()

        with tempfile.TemporaryDirectory(prefix=".vision-rm-",dir=str(log.parent)) as tmp:
            tmp_root=Path(tmp)
            tmp_root.chmod(0o700)
            ready, auth = tmp_root/"ready.pid",tmp_root/"authorized.json"
            try:
                with log.open("x",encoding="utf-8") as output:
                    gate=Path(__file__).with_name("vision_worker_gate.py")
                    handle=subprocess.Popen([
                        "systemd-run","--user","--scope","--unit="+unit,"--",
                        str(python),str(gate),"--ready-file",str(ready),
                        "--auth-file",str(auth),"--gateway",self.base,
                        "--python",str(python),"--script",str(script),"--",*args],
                        stdin=subprocess.DEVNULL,stdout=output,stderr=subprocess.STDOUT,
                        env=env,start_new_session=True)
                    while not ready.is_file():
                        if handle.poll() is not None:
                            raise VisionExecutionError("systemd-run scope exited before handshake")
                        if time.monotonic()-started>12:
                            raise VisionExecutionError("Vision scope worker readiness timeout")
                        time.sleep(.05)
                    worker_pid=int(ready.read_text(encoding="ascii").strip())
                    # systemd-run may notify the child before the scope's
                    # cgroup migration becomes visible in /proc. Wait for
                    # authoritative kernel membership, never trust READY alone.
                    attach_deadline=time.monotonic()+6
                    while True:
                        observed=worker_cgroup_path(worker_pid)
                        members=scoped_processes(scope_path)
                        if observed==scope_path and members is not None and worker_pid in members:
                            break
                        if handle.poll() is not None or time.monotonic()>attach_deadline:
                            raise VisionExecutionError("worker did not enter trusted cgroup scope")
                        time.sleep(.05)
                    resource=call(self.base,"GET","/status")
                    if resource.get("admission_blocked") or resource.get("gpu_residency",{}).get("recovery_required"):
                        raise VisionExecutionError("GPU residency blocked")
                    lease=call(self.base,"POST","/resource/leases",{
                        "source":"vision-benchmark-dev","workload":"vision-benchmark",
                        "priority_class":"background"})
                    lease_id=lease["lease_id"]
                    heart=threading.Thread(target=heartbeat,daemon=True)
                    heart.start()
                    while lease.get("state")!="active":
                        if heartbeat_errors or handle.poll() is not None:
                            raise VisionExecutionError("queue/worker lost")
                        if time.monotonic()-started>queue_timeout_seconds:
                            raise VisionExecutionError("Vision admission timed out")
                        time.sleep(.2)
                        lease=call(self.base,"GET",f"/resource/leases/{lease_id}")
                    use=call(self.base,"POST",f"/resource/leases/{lease_id}/uses",{
                        "provider":"vision-local","capability":"image-analysis",
                        "worker_pid":worker_pid,"scope_path":scope_path})
                    use_id=use["use_id"]
                    payload=json.dumps({"lease_id":lease_id,"use_id":use_id})+"\n"
                    pending=tmp_root/"authorization.tmp"
                    with pending.open("x",encoding="utf-8") as fp:
                        fp.write(payload)
                        fp.flush()
                        os.fsync(fp.fileno())
                    os.replace(pending,auth)

                    began=time.monotonic()
                    while handle.poll() is None:
                        if heartbeat_errors or time.monotonic()-began>max_seconds:
                            raise VisionExecutionError("Vision GPU worker heartbeat/timeout failure")
                        time.sleep(.2)
                    code=handle.wait()
                    members=scope_members_or_terminal(scope_path)
                    if members is None or members:
                        raise VisionExecutionError("scope still populated after worker exit")
                    cleanup=call(self.base,"DELETE",f"/resource/leases/{lease_id}/uses/{use_id}")
                    if cleanup!={"released":True}:
                        raise VisionExecutionError("unverified GPU cleanup")
                    use_id=None
                    if code!=0:
                        raise VisionExecutionError("Vision worker returned nonzero exit")
                    return {"status":"completed","worker_pid":worker_pid,
                            "unit":unit+".scope",
                            "elapsed_seconds":round(time.monotonic()-started,3)}
            finally:
                stop.set()
                # A worker may exit while a detached child remains in its
                # cgroup. Never rely solely on the systemd-run parent PID.
                members=scope_members_or_terminal(scope_path)
                if handle is not None and (handle.poll() is None or members is None or members):
                    self._scope_call(env,"stop",unit+".scope")
                    if handle.poll() is None:
                        try:handle.wait(timeout=4)
                        except subprocess.TimeoutExpired:
                            self._scope_call(env,"kill","--signal=SIGKILL",unit+".scope")
                            handle.wait(timeout=5)
                # Wait briefly for systemd's cgroup release. Absent evidence
                # or surviving descendants fail closed: do not release GPU.
                clear_deadline=time.monotonic()+5
                while True:
                    members=scope_members_or_terminal(scope_path)
                    if members is not None and not members:
                        break
                    if time.monotonic()>=clear_deadline:
                        raise VisionExecutionError("uncertain cgroup state after termination")
                    time.sleep(.05)
                if lease_id and use_id:
                    try:
                        call(self.base,"DELETE",f"/resource/leases/{lease_id}/uses/{use_id}")
                    except Exception:
                        pass
                if lease_id:
                    try:call(self.base,"DELETE",f"/resource/leases/{lease_id}")
                    except Exception:pass
                if heart:heart.join(timeout=2)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--python",type=Path,required=True)
    p.add_argument("--script",type=Path,required=True)
    p.add_argument("--log",type=Path,required=True)
    p.add_argument("--max-seconds",type=int,default=110)
    p.add_argument("args",nargs=argparse.REMAINDER)
    a=p.parse_args()
    args=a.args[1:] if a.args[:1]==["--"] else a.args
    result=ScopedVisionExecutor().execute(python=a.python,script=a.script,args=args,
                                           log=a.log,max_seconds=a.max_seconds)
    print(json.dumps(result))

if __name__=="__main__":main()
