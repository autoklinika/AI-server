"""DEV read-only GPU host boundary audit. No locks, process control or N1 grants.

Positive system-manager DevicePolicy probes prove only the tested transient
cgroups. They do not establish exclusive ownership against host users,
unmanaged processes, other service managers or direct Ollama API clients.

This audit always returns BLOCKED for global GPU grants. It deliberately does
not provide a "safe" or "can_grant" boolean that might be misused as permission.
"""
from __future__ import annotations

import json
from pathlib import Path
import stat
import subprocess
from typing import Callable
from urllib.request import urlopen

GPU_NODES = (
    "/dev/dri/renderD128",
    "/dev/dri/renderD129",
    "/dev/dri/card0",
    "/dev/dri/card1",
    "/dev/kfd",
    "/dev/nvidia0",
    "/dev/nvidiactl",
    "/dev/nvidia-uvm",
    "/dev/nvidia-uvm-tools",
    "/dev/nvidia-modeset",
)
UNITS = ("ai-gateway.service", "ollama.service", "comfyui.service",
         "ai-bridge.service")
GPU_IDS = {"0000:c6:00.0": ("0x1002", "0x150e"),
           "0000:03:00.0": ("0x10de", "0x2d04")}
DIRECT_OLLAMA = "http://127.0.0.1:11434/api/version"


def _proc(argv: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(argv, capture_output=True, text=True, timeout=4,
                          check=False)


def _node(path: str) -> dict[str, object]:
    try:
        s=Path(path).stat()
        return {
            "state": "OBSERVED",
            "character_device": stat.S_ISCHR(s.st_mode),
            "mode": format(stat.S_IMODE(s.st_mode),"04o"),
            "owner_uid":s.st_uid,
            "owner_gid":s.st_gid,
            "world_read":bool(s.st_mode & stat.S_IROTH),
            "world_write":bool(s.st_mode & stat.S_IWOTH),
        }
    except (OSError, ValueError):
        return {"state": "UNKNOWN"}


def _unit(unit: str) -> dict[str, str]:
    keys=("LoadState","ActiveState","MainPID","DevicePolicy",
          "PrivateDevices","ControlGroup","User","MemoryMax")
    try:
        r=_proc(["/usr/bin/systemctl","show",unit,"--no-pager",
                 "--property="+",".join(keys)])
        if r.returncode: return {"state":"UNKNOWN"}
        observed={}
        for line in r.stdout.splitlines():
            k,sep,value=line.partition("=")
            if not sep or k in observed or k not in keys:
                return {"state":"UNKNOWN"}
            observed[k]=value
        if not {"LoadState","ActiveState","MainPID","DevicePolicy"} <= set(observed):
            return {"state":"UNKNOWN"}
        return observed
    except (OSError, subprocess.TimeoutExpired):
        return {"state":"UNKNOWN"}


def _holders(paths: tuple[str,...] = GPU_NODES) -> dict[str, object]:
    # lsof does not prove the absence of hidden file descriptors across UID,
    # namespaces, processes or kernel async queues.
    try:
        r=_proc(["/usr/bin/lsof","-nP","-w","-t",*paths])
        pids=sorted({int(v) for v in r.stdout.splitlines() if v.isdecimal()})
        cgroups={}
        for pid in pids[:50]:
            try:
                rows=Path(f"/proc/{pid}/cgroup").read_text().splitlines()
                line=next((x for x in rows if x.startswith("0::")),"")
                cg=line[3:] if line else "UNKNOWN"
                # Restrict to cgroup path; never record cmdline, env, FDs or prompts.
                cgroups[str(pid)]=cg[:256]
            except (OSError,ValueError):
                cgroups[str(pid)]="UNKNOWN"
        return {"state":"OBSERVED_PARTIAL" if r.returncode in (0,1)
                else "UNKNOWN",
                "pids":pids[:50],
                "cgroups":cgroups,
                "coverage":"PARTIAL_VISIBLE_USERS_ONLY"}
    except (OSError,ValueError,subprocess.TimeoutExpired):
        return {"state":"UNKNOWN","pids":[],
                "coverage":"PARTIAL_VISIBLE_USERS_ONLY"}


def _direct_ollama_api() -> str:
    # Read-only query only, never prompt/inference. Success establishes bypass
    # ability for this host user, not a guarantee for a different principal.
    try:
        with urlopen(DIRECT_OLLAMA,timeout=3) as response:
            if response.status != 200: return "UNKNOWN"
            obj=json.load(response)
            return "REACHABLE_DIRECT" if isinstance(obj,dict) and "version" in obj else "UNKNOWN"
    except (OSError,ValueError,TimeoutError):
        return "UNKNOWN"


def audit(*, node: Callable=_node, unit: Callable=_unit,
          holders: Callable=_holders,
          direct_api: Callable=_direct_ollama_api,
          pci_root: Path=Path("/sys/bus/pci/devices")) -> dict[str, object]:
    checks={"gpu_nodes":{}, "services":{}, "hardware":{},
            "open_gpu_holders":{}, "direct_model_api":"UNKNOWN"}
    findings=[]
    for path in GPU_NODES:
        try: obs=node(path)
        except Exception: obs={"state":"UNKNOWN"}
        checks["gpu_nodes"][path]=obs
        if obs.get("world_write") is True:
            findings.append("WORLD_WRITABLE_GPU_DEVICE")
    for name in UNITS:
        try: obs=unit(name)
        except Exception: obs={"state":"UNKNOWN"}
        checks["services"][name]=obs
        if (obs.get("ActiveState")=="active" and
            obs.get("DevicePolicy") not in ("closed","strict")):
            findings.append("ACTIVE_SERVICE_GPU_ACCESS_NOT_CGROUP_RESTRICTED")
    for bdf,identity in GPU_IDS.items():
        try:
            root=pci_root/bdf
            val=((root/"vendor").read_text().strip(),
                 (root/"device").read_text().strip())
            checks["hardware"][bdf]="IDENTITY_MATCH" if val==identity else "MISMATCH"
        except (OSError,ValueError):
            checks["hardware"][bdf]="UNKNOWN"
    try: checks["open_gpu_holders"]=holders()
    except Exception: checks["open_gpu_holders"]={"state":"UNKNOWN"}
    # Open GPU FDs in *any* unmanaged production engine during RM IDLE
    # are evidence of concurrent access. Even an empty list is NOT an N1 release.
    if checks["open_gpu_holders"].get("pids"):
        findings.append("GPU_FILE_DESCRIPTORS_OBSERVED")
    try: checks["direct_model_api"]=direct_api()
    except Exception: checks["direct_model_api"]="UNKNOWN"
    if checks["direct_model_api"]=="REACHABLE_DIRECT":
        findings.append("DIRECT_OLLAMA_API_REACHABLE_OUTSIDE_GATEWAY")
    return {
        "schema":1,
        "decision":"BLOCKED",
        "global_host_gpu_exclusivity":"NOT_VERIFIED",
        "driver_reuse_safe":"NOT_VERIFIED",
        "n1_gpu_grant":"NOT_ADMITTED",
        "transient_systemd_scope_test":"PASS_REPORTED_SEPARATELY",
        "reason":"TRANSIENT_SCOPE_BOUNDARY_IS_NOT_HOST_WIDE_EXCLUSIVITY",
        "findings":sorted(set(findings)),
        "checks":checks,
    }


def main() -> int:
    result=audit()
    print(json.dumps(result, indent=2,sort_keys=True))
    return 2  # Deliberately denies using the audit as a positive admission.


if __name__=="__main__":
    raise SystemExit(main())
