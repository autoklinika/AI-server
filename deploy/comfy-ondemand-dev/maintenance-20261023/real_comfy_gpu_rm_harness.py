#!/usr/bin/python3
"""Single-run DEV GPU check via the existing RM, with managed transient systemd.

Launched only by the operator-authorized maintenance script after production
Gateway/ComfyUI are stopped. Real ROCm GPU is used. No service is installed.
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import re
import subprocess
import time
from urllib.request import Request, urlopen
from uuid import UUID, uuid4

import httpx

from ai_bridge.gateway.app import create_gateway_app
from ai_bridge.gateway.comfy_ondemand_dev import ServiceIdentity
from ai_bridge.settings import Settings

BASE=Path("/srv/ai-data/staging/comfy-ondemand-maintenance-dev-20261023")
UNIT="ai-rm-comfy-ondemand-dev.service"
CGROUP="/system.slice/"+UNIT
URL="http://127.0.0.1:11657"
MARKER=BASE/"dev-residency.blocked"
RESULT=BASE/"real-comfy-gpu-result.json"
PYTHON="/opt/comfyui/venv/bin/python"
SCRIPT="/opt/comfyui/ComfyUI/main.py"
MODEL_DIR="/opt/comfyui/data/models"
EXPECTED_BOOT=Path("/proc/sys/kernel/random/boot_id").read_text().strip()

def read_url(path, *, method="GET", payload=None, timeout=5):
    data=json.dumps(payload).encode() if payload is not None else None
    req=Request(URL+path,method=method,data=data,
                headers={"Content-Type":"application/json"} if data else {})
    with urlopen(req, timeout=timeout) as resp:
        return json.load(resp)

def command(*args, timeout=12):
    p=subprocess.run(args, text=True, capture_output=True,
                     timeout=timeout,check=False)
    if p.returncode != 0:
        raise RuntimeError("approved DEV service action failed: "+str(args[0]))
    return p.stdout.strip()

def unit_state():
    text=command("/usr/bin/systemctl","--system","show",UNIT,
                 "--property=ActiveState,MainPID,InvocationID,ControlGroup,User,DevicePolicy,Restart,LoadState",
                 "--no-pager",timeout=4)
    return dict(line.split("=",1) for line in text.splitlines() if "=" in line)

def birth(pid):
    return int(Path(f"/proc/{pid}/stat").read_text().rsplit(")",1)[1].split()[19])

class FixedSystemdController:
    def __init__(self):
        self.events=[]
        self.last=None

    def running(self, token):
        try:
            s=unit_state()
            if (s["ActiveState"]!="active" or s["MainPID"]!=str(token.pid) or
                s["InvocationID"]!=token.incarnation or
                s["ControlGroup"]!=token.cgroup or s["User"]!="harrypotter" or
                s["DevicePolicy"]!="closed" or s["Restart"]!="no"):
                return False
            if token.boot_id!=EXPECTED_BOOT or token.cgroup!=CGROUP:
                return False
            p=Path("/proc")/str(token.pid)
            if birth(token.pid)!=token.process_start_ticks:
                return False
            if f"0::{CGROUP}" not in (p/"cgroup").read_text().splitlines():
                return False
            cmd=(p/"cmdline").read_bytes().split(b"\0")
            return (SCRIPT.encode() in cmd and b"11657" in cmd and
                    b"--cpu" not in cmd)
        except (OSError,KeyError,ValueError,RuntimeError):
            return False

    async def start(self):
        self.events.append("start")
        if not MARKER.is_file():
            raise RuntimeError("RM recovery marker not set before GPU start")
        prod=command("/usr/bin/systemctl","--system","show","comfyui.service",
                     "--property=ActiveState","--value",timeout=4)
        gate=command("/usr/bin/systemctl","--system","show","ai-gateway.service",
                     "--property=ActiveState","--value",timeout=4)
        if prod!="inactive" or gate!="inactive":
            raise RuntimeError("production GPU owner/Gateway still running")
        if unit_state()["ActiveState"]!="inactive":
            raise RuntimeError("test unit existed or previous failure not collected")
        args=[
            "/usr/bin/systemd-run","--system","--collect","--service-type=exec",
            "--unit="+UNIT,
            "--uid=harrypotter",
            "--working-directory=/opt/comfyui/ComfyUI",
            "--property=Restart=no",
            "--property=DevicePolicy=closed",
            "--property=DeviceAllow=/dev/kfd rw",
            "--property=DeviceAllow=/dev/dri/renderD128 rw",
            "--property=PrivateDevices=no",
            "--property=NoNewPrivileges=yes",
            "--property=KillMode=control-group",
            "--property=RuntimeMaxSec=240s",
            "--property=TimeoutStopSec=20s",
            "--property=MemoryAccounting=yes",
            "--property=MemoryHigh=7G",
            "--property=MemoryMax=9G",
            "--property=MemorySwapMax=0",
            "--property=TasksMax=192",
            PYTHON,SCRIPT,
            "--listen","127.0.0.1","--port","11657",
            "--disable-auto-launch","--preview-method","none",
            "--models-directory",MODEL_DIR,
            "--input-directory",str(BASE/"input"),
            "--output-directory",str(BASE/"output"),
            "--temp-directory",str(BASE/"temp"),
            "--user-directory",str(BASE/"user"),
        ]
        command(*args,timeout=18)
        end=time.monotonic()+70
        while time.monotonic()<end:
            if unit_state()["ActiveState"]!="active":
                raise RuntimeError("DEV GPU ComfyUI exited at startup")
            try:
                stats=await asyncio.to_thread(read_url,"/system_stats",timeout=2)
                evidence=await asyncio.to_thread(read_url,"/ai-platform/residency",timeout=2)
                if (any("AMD Radeon 890M" in d.get("name","") for d in stats.get("devices",[]))
                        and evidence.get("schema_version")==1):
                    break
            except (OSError,ValueError,KeyError):
                pass
            await asyncio.sleep(.25)
        else:
            raise RuntimeError("DEV ComfyUI GPU readiness/extension not verified")
        s=unit_state()
        pid=int(s["MainPID"])
        token=ServiceIdentity(EXPECTED_BOOT,s["InvocationID"],
                              pid,s["ControlGroup"],birth(pid))
        if not self.running(token):
            raise RuntimeError("DEV systemd identity mismatch")
        # This root-only evidence is deliberately scoped to currently visible GPU holders.
        holders=subprocess.run(["/usr/bin/fuser","/dev/kfd","/dev/dri/renderD128"],
             text=True,capture_output=True,timeout=5)
        pids={int(x) for x in holders.stdout.split() if x.isdecimal()}
        if pids!={pid}:
            raise RuntimeError("unverified AMD GPU owners in DEV maintenance window")
        self.last=token
        self.events.append("ready")
        return token

    async def stop_and_verify(self, token):
        self.events.append("stop")
        if not self.running(token) or not MARKER.is_file():
            raise RuntimeError("DEV process identity changed before stop")
        await asyncio.to_thread(command,"/usr/bin/systemctl","--system","stop",UNIT,timeout=28)
        s=unit_state()
        if s["ActiveState"]!="inactive" or s["MainPID"]!="0":
            raise RuntimeError("DEV systemd unit remained running")
        if Path(f"/proc/{token.pid}").exists():
            raise RuntimeError("DEV ComfyUI PID not absent after stop")
        cg=Path("/sys/fs/cgroup"+CGROUP)
        if cg.is_dir() and (cg/"cgroup.procs").read_text().strip():
            raise RuntimeError("GPU cgroup not empty after stop")
        holders=subprocess.run(["/usr/bin/fuser","/dev/kfd","/dev/dri/renderD128"],
            capture_output=True,text=True,timeout=5)
        if holders.returncode==0 and holders.stdout.strip():
            raise RuntimeError("AMD GPU file descriptors still exist after DEV stop")
        if holders.returncode not in (0,1):
            raise RuntimeError("cannot verify AMD process owners after stop")
        self.events.append("stopped")


def mocked_ollama(req):
    if req.url.path in ("/api/ps","/api/tags"):
        return httpx.Response(200,json={"models":[]})
    return httpx.Response(200,json={"done":True})

def fixed_observation():
    with urlopen("http://127.0.0.1:8188/queue",timeout=1):
        # Production port must be gone during DEV window, even if it responds.
        raise RuntimeError("production ComfyUI HTTP is unexpectedly reachable")

async def exercise():
    if MARKER.exists() or RESULT.exists():
        raise RuntimeError("previous blocked DEV evidence prevents a new attempt")
    if UNIT!="ai-rm-comfy-ondemand-dev.service":
        raise RuntimeError("unit identity mismatch")
    s=unit_state()
    if s["ActiveState"]!="inactive" or s["MainPID"]!="0":
        raise RuntimeError("DEV unit has an existing process")
    for service in ("comfyui.service","ai-gateway.service"):
        if command("/usr/bin/systemctl","--system","show",service,
                   "--property=ActiveState","--value",timeout=5)!="inactive":
            raise RuntimeError("legacy service still running "+service)
    try:
        fixed_observation()
    except (OSError,TimeoutError):
        pass
    # Never create workdirs as root while the ComfyUI process runs nonroot.
    # Enforce ownership/permissions even when harness is called without runner.
    import stat
    for folder in ("input","output","temp","user"):
        path=BASE/folder
        if path.is_symlink() or not path.is_dir():
            raise RuntimeError("DEV workdir missing or symlinked")
        metadata=path.stat()
        if (metadata.st_uid!=1000 or metadata.st_gid!=1000 or
            stat.S_IMODE(metadata.st_mode)!=0o700):
            raise RuntimeError("DEV ComfyUI user lacks owner/mode on workdir")
    ctrl=FixedSystemdController()
    report={"schema":1,"started_local":time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "verdict":"INCOMPLETE","scope":"DEV transient system-manager real ROCm",
            "production_unchanged":False,
            "gpu_reuse_safe":"NOT_VERIFIED","n1_gpu_grants":"NOT_ADMITTED"}
    try:
        settings=Settings(
            _env_file=None,
            gateway_host="127.0.0.1",
            ollama_url="http://mocked-ollama.invalid",
            gateway_comfy_url=URL,
            gateway_gpu_marker=MARKER,
            gateway_comfy_ondemand_dev_mode=True,
            gateway_gpu_transition_timeout=35,
            gateway_comfy_idle_reserve_bytes=67108864,
            gateway_max_concurrency=1,
            gateway_vision_radio_enabled=False,
        )
        app=create_gateway_app(settings,comfy_process_controller=ctrl,
            upstream_transport=httpx.MockTransport(mocked_ollama))
        async with app.router.lifespan_context(app):
            # Prevent legacy SIGCONT handling of the stopped production unit.
            app.state.resource_leases.residency.resume_comfy=None
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://dev-gateway",timeout=100) as client:
                lease=(await client.post("/resource/leases",json={
                    "source":"DEV-Hermes-foto",
                    "priority":50,"workload":"media-image"})).json()
                lid=lease["lease_id"]
                api=f"/resource/leases/{lid}"
                started=await client.post(api+"/uses",json={
                    "provider":"comfyui-local","capability":"image-generation"})
                if started.status_code!=201:
                    raise RuntimeError("DEV RM refused real ComfyUI start/lease")
                useid=started.json()["use_id"]
                if not ctrl.last or not ctrl.running(ctrl.last):
                    raise RuntimeError("managed GPU process identity was not verified")
                result=await asyncio.to_thread(read_url,"/ai-platform/residency",timeout=4)
                if not (result.get("schema_version")==1 and
                        result.get("queue_running")==0 and
                        result.get("queue_pending")==0 and
                        result.get("loaded_models")==0):
                    raise RuntimeError("ComfyUI media readiness missing")
                snap=(await client.get("/status")).json()
                if snap["active_count"]!=1 or snap["gpu_residency"]["state"]!="media":
                    raise RuntimeError("one global RM lease not retained")
                print("GPU_DEV_COMFY_STARTED",ctrl.last.pid,flush=True)
                workflow={
                    "1":{"class_type":"EmptyFlux2LatentImage",
                         "inputs":{"width":64,"height":64,"batch_size":1}},
                    "2":{"class_type":"VAELoader",
                         "inputs":{"vae_name":"flux2-vae.safetensors"}},
                    "3":{"class_type":"VAEDecode",
                         "inputs":{"samples":["1",0],"vae":["2",0]}},
                    "4":{"class_type":"SaveImage",
                         "inputs":{"images":["3",0],
                                   "filename_prefix":"rm-comfy-dev-flux2-vae"}},
                }
                response=await asyncio.to_thread(read_url,"/prompt",
                    method="POST",payload={"prompt":workflow,"client_id":str(uuid4())},
                    timeout=8)
                uid=response.get("prompt_id")
                if not isinstance(uid,str) or not uid:
                    raise RuntimeError("ComfyUI rejected GPU VAE test workflow")
                deadline=time.monotonic()+85
                final=None
                while time.monotonic()<deadline:
                    hist=await asyncio.to_thread(read_url,"/history/"+uid,timeout=4)
                    obj=hist.get(uid)
                    if obj and obj.get("status",{}).get("status_str")=="error":
                        raise RuntimeError("ComfyUI reports workflow failed")
                    if obj and obj.get("outputs",{}).get("4",{}).get("images"):
                        final=obj
                        break
                    await asyncio.sleep(.3)
                if final is None:
                    raise RuntimeError("GPU VAE workflow did not complete in bounded window")
                name=final["outputs"]["4"]["images"][0].get("filename","")
                if (not isinstance(name,str) or not re.fullmatch(
                    r"[A-Za-z0-9_.-]+\.png",name) or ".." in name):
                    raise RuntimeError("unsafe or missing generated filename")
                png=BASE/"output"/name
                raw=png.read_bytes()
                if raw[:8]!=b"\x89PNG\r\n\x1a\n":
                    raise RuntimeError("ComfyUI image output is not a PNG")
                dimensions=[int.from_bytes(raw[16:20],"big"),
                            int.from_bytes(raw[20:24],"big")]
                if dimensions!=[64,64]:
                    raise RuntimeError("GPU VAE did not produce 64x64 image")
                report["image"]={"width":dimensions[0],"height":dimensions[1],
                                 "bytes":len(raw)}
                print("GPU_DEV_COMFY_REAL_IMAGE_PASS",dimensions,len(raw),flush=True)
                waiting=asyncio.create_task(client.post("/api/embed",
                    json={"model":"bge-m3","input":"blocked until Comfy cleanup"}))
                await asyncio.sleep(.05)
                if waiting.done():
                    raise RuntimeError("DEV Resource Manager queue bypass")
                if not (await client.delete(api)).json()["released"]:
                    raise RuntimeError("cannot arrange lease release")
                deleted=await client.delete(api+"/uses/"+useid)
                if deleted.status_code!=200:
                    raise RuntimeError("DEV ComfyUI shutdown not verified")
                queued=await asyncio.wait_for(waiting,4)
                if queued.status_code!=200:
                    raise RuntimeError("queued request not unblocked after cleanup")
                end=(await client.get("/status")).json()
                if (end["gpu_residency"]["state"]!="llm" or
                    end["active_count"]!=0 or end["queued_count"]!=0 or
                    end["resource_leases"]["lease_count"]!=0):
                    raise RuntimeError("DEV RM did not release ownership")
                if MARKER.exists():
                    raise RuntimeError("DEV GPU recovery marker still set")
                if ctrl.events!=["start","ready","stop","stopped"]:
                    raise RuntimeError("unexpected managed process lifecycle")
                report["events"]=ctrl.events
                report["scheduler"]="single_existing_RM_queue"
                report["real_vae_decode"]="PASS"
                report["process_stop"]="PASS"
                report["verdict"]="PASS"
    except BaseException as e:
        report["failure_class"]=type(e).__name__
        print("REAL_COMFY_DEV_FAIL_CLOSED",type(e).__name__,flush=True)
        raise
    finally:
        report["finished_local"]=time.strftime("%Y-%m-%dT%H:%M:%S%z")
        report["recovery_marker_left"]=MARKER.exists()
        RESULT.write_text(json.dumps(report,sort_keys=True,indent=2)+"\n")
    print("REAL_COMFY_DEV_GPU_CYCLE_PASS",flush=True)


if __name__=="__main__":
    asyncio.run(exercise())
