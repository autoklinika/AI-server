#!/usr/bin/python3
"""One-shot fixed-device open checks inside an *operator-started system* cgroup.

No ioctls, kernels, model loads or device changes. Must NOT be interpreted as
host-wide GPU exclusivity or N1 approval. Run with systemd-run --system, --uid.
"""
import errno
import os
from pathlib import Path
import sys

MODES = {
    "amd": {
        "permitted": ("/dev/dri/renderD128",),
        "forbidden": ("/dev/dri/renderD129","/dev/nvidia0","/dev/kfd"),
        "device":"0000:c6:00.0",
    },
    "rtx": {
        "permitted": ("/dev/nvidia0","/dev/nvidiactl"),
        "forbidden": ("/dev/dri/renderD128","/dev/kfd"),
        "device":"0000:03:00.0",
    },
}

def open_result(path):
    try:
        fd=os.open(path,os.O_RDONLY|os.O_CLOEXEC|os.O_NONBLOCK)
    except OSError as e:
        return "ACCESS_DENIED" if e.errno in (errno.EPERM,errno.EACCES) else "UNKNOWN"
    os.close(fd)
    return "ACCESS_GRANTED"

def evaluate(kind):
    if kind not in MODES:
        raise ValueError("fixed GPU role must be amd or rtx")
    spec=MODES[kind]
    cg=Path("/proc/self/cgroup").read_text().strip()
    if not cg.startswith("0::/system.slice/ai-rm-dev-"):
        raise RuntimeError("not launched in the authorized transient SYSTEM cgroup")
    vendor_path=Path("/sys/bus/pci/devices")/spec["device"]/"vendor"
    actual=vendor_path.read_text().strip()
    if actual!=("0x1002" if kind=="amd" else "0x10de"):
        raise RuntimeError("wrong physical PCI identity")
    outcomes={p:open_result(p) for p in spec["permitted"]+spec["forbidden"]}
    print("FIXED_ROLE",kind,"CGROUP_CLASS=system.slice","ACCESS",outcomes,flush=True)
    if any(outcomes[p]!="ACCESS_GRANTED" for p in spec["permitted"]):
        raise RuntimeError("required intended GPU access not available")
    if any(outcomes[p]!="ACCESS_DENIED" for p in spec["forbidden"]):
        raise RuntimeError("forbidden GPU access was not denied")
    print("SYSTEM_SCOPE_DEVICE_BOUNDARY_PASS",kind,flush=True)

if __name__=="__main__":
    if len(sys.argv)!=2 or sys.argv[1] not in MODES:
        raise SystemExit("usage: os_gpu_access_probe.py amd|rtx")
    evaluate(sys.argv[1])
