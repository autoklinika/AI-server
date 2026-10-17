"""Fixed pilot payload. No CLI workloads; parent authorization is mandatory.

Do not execute in DEV. Import is inert (including no torch import). This is
worker-local synchronization only, never a driver/global reuse certificate.
"""
from __future__ import annotations

import json
from pathlib import Path
import re
import sys

WORKLOAD = "rocm-matmul-64-v1"
EXPECTED_PCI = "0000:c6:00.0"


def _hip_bus_id(torch) -> str:
    """Query HIP's documented ordinal-to-PCI ABI, not a guessed torch ordinal.

    The installed ROCm wheel bundles libamdhip64. The library path is derived
    only from the imported trusted torch package, never client input.
    """
    import ctypes

    torch_file = getattr(torch, "__file__", None)
    if not isinstance(torch_file, str):
        raise RuntimeError("trusted ROCm torch path unavailable")
    lib = Path(torch_file).resolve().parents[1] / "_rocm_sdk_core/lib/libamdhip64.so.7"
    if not lib.is_file():
        raise RuntimeError("HIP device-binding ABI unavailable")
    hip = ctypes.CDLL(str(lib))
    fn = hip.hipDeviceGetPCIBusId
    fn.argtypes = (ctypes.POINTER(ctypes.c_char), ctypes.c_int, ctypes.c_int)
    fn.restype = ctypes.c_int
    buf = ctypes.create_string_buffer(64)
    if fn(buf, 64, 0) != 0:
        raise RuntimeError("HIP PCI binding lookup failed")
    try:
        return buf.value.decode("ascii")
    except UnicodeDecodeError as exc:
        raise RuntimeError("HIP PCI binding invalid") from exc


def run_fixed(torch, *, pci_root=Path("/sys/bus/pci/devices"), hip_bus_id=None) -> dict:
    """torch injection is for CPU unit tests, not runtime configuration."""
    if not isinstance(torch.version.hip, str) or not torch.version.hip.strip():
        raise RuntimeError("ROCm runtime required")
    if torch.cuda.device_count() != 1:
        raise RuntimeError("exactly one visible device required")
    props = torch.cuda.get_device_properties(0)
    if getattr(props, "gcnArchName", "").split(":", 1)[0] != "gfx1150":
        raise RuntimeError("unexpected GPU architecture")
    # torch's pci_bus_id field is not portable. Use HIP's documented
    # hipDeviceGetPCIBusId ABI when that optional field is absent.
    # Missing/malformed HIP data still denies execution.
    bdf = getattr(props, "pci_bus_id", None)
    if bdf is None:
        bdf = (hip_bus_id or _hip_bus_id)(torch)
    if not isinstance(bdf, str) or not re.fullmatch(
            r"[0-9a-fA-F]{4}:[0-9a-fA-F]{2}:[0-1][0-9a-fA-F]\.[0-7]", bdf):
        raise RuntimeError("runtime PCI binding unavailable")
    if bdf.lower() != EXPECTED_PCI:
        raise RuntimeError("wrong runtime PCI binding")
    pci = pci_root / EXPECTED_PCI
    if ((pci / "vendor").read_text().strip() != "0x1002"
            or (pci / "device").read_text().strip() != "0x150e"):
        raise RuntimeError("wrong sysfs PCI binding")
    torch.cuda.set_device(0)
    a = b = c = None
    try:
        a = torch.ones((64, 64), device="cuda:0", dtype=torch.float32)
        b = torch.ones((64, 64), device="cuda:0", dtype=torch.float32)
        c = torch.matmul(a, b)
        torch.cuda.synchronize(0)
        if not torch.all(c == 64).item():
            raise RuntimeError("incorrect fixed result")
    finally:
        a = b = c = None
        torch.cuda.empty_cache()
        torch.cuda.synchronize(0)
    return {"schema": 1, "workload": WORKLOAD, "pci_bdf": EXPECTED_PCI,
            "local_synced": True, "status": "WORKER_LOCAL_SYNC"}


def main() -> int:
    if len(sys.argv) != 1:
        return 2
    try:
        import torch
        result = run_fixed(torch)
    except Exception:
        print(json.dumps({"schema": 1, "status": "WORKER_FAILED"}))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
