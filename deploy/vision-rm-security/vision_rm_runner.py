#!/usr/bin/env python3
"""Root-installed, ai-vision UID, model-only Vision worker supervisor.

The supervisor has NO RM bearer. One fixed root-owned manifest is executed
through a dedicated systemd user scope only after broker admission.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import secrets
import socket
import stat
import struct
import subprocess
import sys
import tempfile
import time

BROKER = Path("/run/ai-vision-rm-broker/control.sock")
MANIFEST = Path("/usr/local/share/ai-platform/vision-rm/job.json")
GATE = Path("/usr/local/libexec/ai-platform/vision-worker-gate.py")
LOG_ROOT = Path("/srv/ai-data/evaluation/vision-rm-service")
GATEWAY = os.environ.get("VISION_RM_GATEWAY_URL", "http://127.0.0.1:11575")


def request(message: dict) -> dict:
    with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as conn:
        conn.settimeout(12)
        conn.connect(str(BROKER))
        _, peer_uid, _ = struct.unpack("3i", conn.getsockopt(
            socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i")))
        if peer_uid != 993:
            raise RuntimeError("broker peer denied")
        conn.sendall(json.dumps(message,separators=(",",":")).encode("ascii"))
        payload=bytearray()
        while len(payload)<=8192 and b"\n" not in payload:
            part=conn.recv(4096)
            if not part:
                break
            payload.extend(part)
    if len(payload)>8192 or payload.count(b"\n")!=1:
        raise RuntimeError("broker reply invalid")
    return json.loads(payload)


def fixed_manifest() -> dict:
    if not MANIFEST.is_file() or MANIFEST.is_symlink():
        raise RuntimeError("benchmark manifest absent")
    st=MANIFEST.stat()
    if st.st_uid!=0 or st.st_mode & 0o022:
        raise RuntimeError("untrusted benchmark manifest")
    doc=json.loads(MANIFEST.read_text())
    if set(doc)!={"python","script","args","max_seconds"}:
        raise RuntimeError("manifest schema mismatch")
    if (not isinstance(doc["python"],str) or not isinstance(doc["script"],str)
            or not isinstance(doc["args"],list) or len(doc["args"])>80
            or any(type(x) is not str or len(x)>2048 for x in doc["args"])
            or type(doc["max_seconds"]) is not int or not 10<=doc["max_seconds"]<=120):
        raise RuntimeError("invalid benchmark manifest")
    for key in ("python","script"):
        path=Path(doc[key])
        if not path.is_absolute() or not path.is_file():
            raise RuntimeError("unavailable pinned program")
    return doc


def scope_members(path: str):
    source=Path("/sys/fs/cgroup")/path.lstrip("/")/"cgroup.procs"
    try:
        return {int(pid) for pid in source.read_text().split()}
    except FileNotFoundError:
        # Not a cleanup proof by itself: after terminal parent confirm.
        return None
    except (OSError,ValueError):
        return None


def cleanup(handle, *, unit: str, env: dict, session: str | None) -> list[dict]:
    """Best effort stopping plus independent finish; return only fixed safe codes."""
    failures=[]
    if handle is not None:
        try:
            stopped=subprocess.run(["systemctl","--user","stop",unit+".scope"],
                                   env=env,capture_output=True,timeout=8,check=False)
            if stopped.returncode != 0:
                failures.append({"stage":"scope_stop", "reason":"command_failed"})
            try:
                handle.wait(timeout=6)
            except subprocess.TimeoutExpired:
                subprocess.run(["systemctl","--user","kill","--signal=SIGKILL",unit+".scope"],
                               env=env,capture_output=True,timeout=6,check=False)
                handle.wait(timeout=6)
        except Exception:
            failures.append({"stage":"scope_stop", "reason":"stop_unverified"})
    if session is not None:
        try:
            reply=request({"op":"finish","session":session})
            if reply != {"status":"released"}:
                failure={"stage":"finish", "reason":"invalid_response"}
                if isinstance(reply,dict):
                    if reply.get("status") in ("denied","gateway_error"):
                        failure["reason"]=reply["status"]
                    elif (reply.get("status")=="cleanup_failed"
                          and reply.get("stage") in ("use_cleanup","lease_release")
                          and reply.get("reason") in ("admission_outcome_unknown","unauthorized",
                              "http_error","transport_error","gateway_error","release_unverified")):
                        failure={"stage":reply["stage"], "reason":reply["reason"]}
                        code=reply.get("http_status")
                        if type(code) is int and 100<=code<=599:
                            failure["http_status"]=code
                failures.append(failure)
        except Exception:
            failures.append({"stage":"finish", "reason":"ipc_error"})
    return failures


def finalize(handle, *, unit: str, env: dict, session: str | None,
             primary: BaseException | None, primary_stage: str) -> None:
    failures=cleanup(handle,unit=unit,env=env,session=session)
    if failures or primary is not None:
        # Caller supplies only internal stage constants. Never print the exception.
        diagnostic={"event":"vision_runner_failure", "primary_stage":primary_stage if primary else None,
                    "primary_reason":"execution_error" if primary else None,
                    "cleanup":failures}
        print(json.dumps(diagnostic,separators=(",",":")),file=sys.stderr)
    if failures:
        if primary is not None:
            primary.add_note("Vision cleanup unverified; see sanitized diagnostic")
        else:
            raise RuntimeError("Vision RM cleanup not verified; retain blocked lease")


def run() -> None:
    if os.geteuid()!=__import__("pwd").getpwnam("ai-vision").pw_uid:
        raise RuntimeError("only ai-vision service identity permitted")
    doc=fixed_manifest()
    uid=os.getuid()
    bus=f"/run/user/{uid}/bus"
    if not Path(bus).is_socket():
        raise RuntimeError("systemd ai-vision user bus unavailable")
    env=os.environ.copy()
    for name in list(env):
        if name.startswith("VISION_RM_EXECUTOR_TOKEN") or name.startswith("AI_BRIDGE_PLATFORM_API_TOKEN"):
            env.pop(name)
    env.update({"XDG_RUNTIME_DIR":f"/run/user/{uid}",
                "DBUS_SESSION_BUS_ADDRESS":f"unix:path={bus}"})
    unit="vision-bench-"+secrets.token_hex(6)
    scope=f"/user.slice/user-{uid}.slice/user@{uid}.service/app.slice/{unit}.scope"
    session=None
    handle=None
    LOG_ROOT.mkdir(parents=True,exist_ok=True)
    jobroot=Path(tempfile.mkdtemp(prefix="rm-job-",dir=str(LOG_ROOT)))
    jobroot.chmod(0o700)
    ready,auth=jobroot/"ready.pid",jobroot/"authorized.json"
    log=jobroot/"worker.log"
    stage="worker_start"
    try:
        with log.open("x") as out:
            handle=subprocess.Popen([
                "systemd-run","--user","--scope","--unit="+unit,"--",
                doc["python"],str(GATE),
                "--ready-file",str(ready),"--auth-file",str(auth),
                "--gateway",GATEWAY,"--python",doc["python"],
                "--script",doc["script"],"--",*doc["args"]],
                env=env,stdin=subprocess.DEVNULL,stdout=out,
                stderr=subprocess.STDOUT,start_new_session=True)
        end=time.monotonic()+12
        while not ready.is_file():
            if handle.poll() is not None or time.monotonic()>end:
                raise RuntimeError("parked Vision worker did not start")
            time.sleep(.05)
        pid=int(ready.read_text().strip())
        end=time.monotonic()+7
        while True:
            members=scope_members(scope)
            cg=Path(f"/proc/{pid}/cgroup").read_text()
            if members is not None and pid in members and cg.strip()==f"0::{scope}":
                break
            if time.monotonic()>end or handle.poll() is not None:
                raise RuntimeError("worker did not enter dedicated cgroup")
            time.sleep(.05)
        stage="reservation"
        created=request({"op":"create"})
        if created.get("status")!="ok":
            raise RuntimeError("broker refused reservation")
        session=created["session"]
        stage="queue"
        queue_limit=time.monotonic()+90
        while True:
            state=request({"op":"poll","session":session})
            if state=={"status":"ok","state":"active"}:
                break
            if state.get("status")!="ok" or time.monotonic()>queue_limit:
                raise RuntimeError("GPU queue not admitted")
            if handle.poll() is not None:
                raise RuntimeError("Vision worker exited before GPU admission")
            time.sleep(.2)
        stage="admission"
        response=request({"op":"begin","session":session,
                          "worker_pid":pid,"scope_path":scope})
        if response.get("status")!="ok":
            raise RuntimeError("Vision admission refused by broker")
        stage="authorization"
        token=response["authorization"]
        if set(token)!={"lease_id","use_id","worker_token"}:
            raise RuntimeError("broker returned invalid scoped authorization")
        # Parent-controlled private file gate. Child has only limited read-only
        # use capability: no RM bearer and no authority to modify lease.
        pending=jobroot/"authorization.pending"
        pending.write_text(json.dumps(token)+"\n")
        pending.chmod(0o600)
        os.replace(pending,auth)
        stage="worker_execution"
        began=time.monotonic()
        while handle.poll() is None:
            if time.monotonic()-began>doc["max_seconds"]:
                raise RuntimeError("Vision benchmark exceeded time budget")
            time.sleep(.15)
        if handle.returncode!=0:
            raise RuntimeError("Vision benchmark exited nonzero")
    finally:
        finalize(handle,unit=unit,env=env,session=session,
                 primary=sys.exc_info()[1],primary_stage=stage)
    print("ISOLATED_VISION_BROKER_RUNNER=PASS")


if __name__=="__main__":
    try:
        run()
    except BaseException:
        # Raw tracebacks can include private paths or remote exception content.
        print('{"event":"vision_runner_failed"}',file=sys.stderr)
        sys.exit(1)
