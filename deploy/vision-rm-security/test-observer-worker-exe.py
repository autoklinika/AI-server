#!/usr/bin/env python3
"""Read-only real cross-UID process-exe test with no accelerator workload.

Run only as administrator. Creates one short-lived ai-vision CPU process;
asks observer as ai-gateway-rm and ai-vision, validates policy, then cleans up.
"""
from __future__ import annotations

import json
import os
import pwd
from pathlib import Path
import select
import signal
import subprocess
import sys

SOCKET = "/run/ai-vision-gpu-observer/observer.sock"
QUERY = r"""
import json,socket,sys
pid=int(sys.argv[1]); birth=int(sys.argv[2]); sock=sys.argv[3]
with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as client:
    client.settimeout(4)
    client.connect(sock)
    client.sendall(json.dumps({"op":"inspect_worker","version":1,
                               "pid":pid,"birth":birth},separators=(",",":")).encode()+b"\n")
    value=b""
    while b"\n" not in value and len(value)<8192:
        part=client.recv(1024)
        if not part:break
        value+=part
    assert len(value)<=8192
    assert value.count(b"\n")==1
    obj=json.loads(value)
    assert obj.get("schema_version")==1
    print(json.dumps(obj,sort_keys=True))
"""


def probe(account: str, pid: int, birth: int) -> dict:
    result=subprocess.run(["runuser","-u",account,"--","/usr/bin/python3",
                           "-c",QUERY,str(pid),str(birth),SOCKET],
                           text=True,capture_output=True,timeout=9,check=False)
    if result.returncode!=0:
        raise RuntimeError(f"{account} failed to request observer status")
    return json.loads(result.stdout)


def main() -> None:
    if os.geteuid()!=0:
        raise SystemExit("root required to impersonate only two service UIDs")
    if not Path(SOCKET).is_socket():
        raise SystemExit("observer socket missing")
    child=subprocess.Popen(["runuser","-u","ai-vision","--","/usr/bin/python3",
            "-u","-c","import os,time;print(os.getpid(),flush=True);time.sleep(30)"],
            stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,
            start_new_session=True)
    pid=None
    try:
        readable,_,_=select.select([child.stdout],[],[],6)
        if not readable:raise RuntimeError("ai-vision subprocess readiness timeout")
        pid=int(child.stdout.readline().strip())
        if pid<=1 or Path(f"/proc/{pid}").stat().st_uid!=pwd.getpwnam("ai-vision").pw_uid:
            raise RuntimeError("unexpected subprocess UID")
        statline=Path(f"/proc/{pid}/stat").read_text().rsplit(")",1)[1].strip().split()
        birth=int(statline[19])
        if birth<=0:raise RuntimeError("unavailable kernel PID birth")
        expected=Path(os.readlink(f"/proc/{pid}/exe")).resolve(strict=True)

        allowed=probe("ai-gateway-rm",pid,birth)
        assert allowed["status"]=="ok", "controller cannot verify worker executable"
        worker=allowed["worker"]
        assert worker["pid"]==pid and worker["birth"]==birth
        assert worker["uid"]==Path(f"/proc/{pid}").stat().st_uid
        assert Path(worker["exe"]).resolve(strict=True)==expected
        print("CROSS_UID_EXE_ATTESTATION=PASS")

        wrong_birth=probe("ai-gateway-rm",pid,birth+1)
        assert wrong_birth["status"]=="evidence_unavailable"
        print("STALE_PID_BIRTH=DENIED")

        forbidden=probe("ai-vision",pid,birth)
        assert forbidden["status"]=="denied"
        print("MODEL_EXE_INSPECTION=DENIED")
    finally:
        try:os.killpg(child.pid,signal.SIGTERM)
        except ProcessLookupError:pass
        try:child.wait(timeout=4)
        except subprocess.TimeoutExpired:
            try:os.killpg(child.pid,signal.SIGKILL)
            except ProcessLookupError:pass
            child.wait(timeout=4)
        if child.stdout:child.stdout.close()
        if pid is not None and Path(f"/proc/{pid}").exists():
            raise RuntimeError("temporary ai-vision process remains after test")
    print("TEMPORARY_WORKER_CLEANUP=PASS")
    print("OBSERVER_WORKER_EXE_E2E=PASS")


if __name__=="__main__":
    main()
