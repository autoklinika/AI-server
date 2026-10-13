#!/usr/bin/env python3
"""Single-use operator-authorized GPU experiment under Gateway queue reservation.

NOT a formal Vision GPU resource lease! Current Gateway cannot register Vision
as a provider-specific external use. Guard only blocks gateway-admitted LLM work
for a short manual maintenance window and fails closed on unsafe conditions.
No service stop, no Ollama direct generate, no driver changes.
"""
from __future__ import annotations
import argparse
import json
import os
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from urllib.request import Request,urlopen

BASE="http://127.0.0.1:11435"
OLLAMA="http://127.0.0.1:11434"

def api(url:str,method="GET",body=None):
    data=json.dumps(body).encode() if body is not None else None
    req=Request(url,data=data,method=method,headers={"Content-Type":"application/json"} if data else {})
    with urlopen(req,timeout=7) as r:
        return json.load(r)

def baseline():
    gateway=api(BASE+"/status")
    if gateway.get("admission_blocked") or gateway.get("active") or gateway.get("queued"):
        raise RuntimeError("Gateway has blocked/active/queued jobs")
    if gateway.get("gpu_residency",{}).get("state")!="llm" or gateway.get("gpu_residency",{}).get("recovery_required"):
        raise RuntimeError("GPU residency is not clean llm state")
    if gateway.get("resource_leases",{}).get("lease_count")!=0:
        raise RuntimeError("Gateway has active leases")
    inventory=api(OLLAMA+"/api/ps")
    if inventory.get("models"):
        raise RuntimeError("Ollama has resident models; use Gateway GPU cleanup path first")

def heartbeat(stop:threading.Event,lease:str,errors:list):
    while not stop.wait(8):
        try:
            status=api(BASE+"/resource/leases/"+lease+"/heartbeat",method="POST")
            if status.get("state")!="active":
                raise RuntimeError("Gateway lease lost active ownership")
        except Exception as exc:
            errors.append(repr(exc))
            stop.set()

def run(args):
    baseline()
    lease_id=None
    stop=threading.Event()
    errors=[]
    t=None
    started=time.monotonic()
    try:
        leased=api(BASE+"/resource/leases",method="POST",
                   body={"source":"vision-rocm-one-shot-test","priority_class":"background","workload":"external"})
        lease_id=leased["lease_id"]
        if leased.get("state")!="active":raise RuntimeError("lease was not admitted")
        if api(OLLAMA+"/api/ps").get("models"):
            raise RuntimeError("Ollama residents appeared while acquiring lease")
        status=api(BASE+"/status")
        active=status.get("active") or []
        if len(active)!=1 or status["resource_leases"]["lease_count"]!=1 or status["gpu_residency"]["state"]!="llm":
            raise RuntimeError("Gateway reservation is not exclusive")
        print("MAINTENANCE_QUEUE_RESERVATION=ACTIVE (not provider-specific use)",flush=True)
        t=threading.Thread(target=heartbeat,args=(stop,lease_id,errors),daemon=True)
        t.start()
        env=os.environ.copy()
        env.update({
          "ROCR_VISIBLE_DEVICES":"0","HIP_VISIBLE_DEVICES":"0",
          "OMP_NUM_THREADS":"2","MKL_NUM_THREADS":"2",
          "PYTORCH_HIP_ALLOC_CONF":"max_split_size_mb:32"
        })
        passthrough = args.smoke_args[1:] if args.smoke_args[:1] == ["--"] else args.smoke_args
        cmd=[str(args.python),str(args.smoke),args.output_flag,str(args.output),*passthrough]
        # Poll the heartbeat state while the worker is running. A lost lease
        # must terminate GPU execution immediately, not after the subprocess ends.
        # Use a file for output to avoid deadlocking on a full stdout pipe.
        with tempfile.TemporaryFile(mode="w+t", encoding="utf-8") as log:
            with subprocess.Popen(cmd, env=env, stdout=log,
                                  stderr=subprocess.STDOUT, text=True,
                                  start_new_session=True) as worker:
                deadline=time.monotonic()+args.timeout
                while worker.poll() is None:
                    if errors or time.monotonic()>deadline:
                        worker.terminate()
                        try: worker.wait(timeout=4)
                        except subprocess.TimeoutExpired:
                            worker.kill()
                            worker.wait(timeout=5)
                        raise RuntimeError("Vision GPU worker aborted: lease heartbeat or time limit")
                    time.sleep(.20)
                code=worker.returncode
            log.seek(0)
            output=log.read()
        print(output[-4500:],flush=True)
        if errors:
            raise RuntimeError("Heartbeat failure during GPU test: "+repr(errors))
        if code!=0:
            raise RuntimeError(f"GPU smoke failed with exit={code}")
        status=api(BASE+"/status")
        if status.get("gpu_residency",{}).get("recovery_required"):
            raise RuntimeError("Gateway recovery flag set")
        print("ONE_SHOT_ROCM_SMOKE_EXIT=PASS elapsed="+str(round(time.monotonic()-started,2)),flush=True)
    finally:
        stop.set()
        if t:t.join(timeout=3)
        if lease_id:
            try:
                print("MAINTENANCE_LEASE_RELEASE",api(BASE+"/resource/leases/"+lease_id,method="DELETE"),flush=True)
            except Exception as exc:
                print("MAINTENANCE_LEASE_RELEASE_FAILED",repr(exc),flush=True)
                raise

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python",type=Path,required=True)
    parser.add_argument("--smoke",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--timeout",type=int,default=90)
    parser.add_argument("--output-flag", choices=["--output", "--out"], default="--output")
    parser.add_argument("smoke_args",nargs=argparse.REMAINDER)
    args=parser.parse_args()
    if not 10<=args.timeout<=120:parser.error("timeout must be 10..120")
    run(args)

if __name__=="__main__":
    main()
