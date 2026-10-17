#!/usr/bin/env python3
"""Short ROCm/PyTorch gfx1150 GPU compatibility smoke; no WinCLIP or Ollama writes.

This script does NOT acquire Gateway resource ownership. Invoke ONLY through
controlled one-shot maintenance reservation after production idle preflight.
"""
from __future__ import annotations
import argparse
import json
import os
import platform
import time
from pathlib import Path


def run():
    import torch
    result = {
        "status": "preflight",
        "host_kernel": platform.release(),
        "python": platform.python_version(),
        "torch": torch.__version__,
        "torch_hip": torch.version.hip,
        "device_available": torch.cuda.is_available(),
        "visible_devices": torch.cuda.device_count(),
    }
    if not torch.version.hip or not torch.cuda.is_available():
        raise RuntimeError("no ROCm HIP GPU available")
    if torch.cuda.device_count() != 1:
        raise RuntimeError("expected exactly one visible GPU")
    name = torch.cuda.get_device_name(0)
    props = torch.cuda.get_device_properties(0)
    result["device_name"] = name
    result["device_total_memory_bytes"] = int(props.total_memory)
    result["device_gcn_arch"] = getattr(props, "gcnArchName", "unknown")
    if "gfx1150" not in str(result["device_gcn_arch"]):
        raise RuntimeError("architecture mismatch; expected gfx1150")
    # Only small allocations; no heavy benchmark until isolated compatibility is proven.
    torch.manual_seed(20261013)
    size = 512
    a = torch.randn((size,size),device="cuda",dtype=torch.float16)
    b = torch.randn((size,size),device="cuda",dtype=torch.float16)
    torch.cuda.synchronize()
    start = time.perf_counter()
    c = a @ b
    torch.cuda.synchronize()
    result["small_matmul_seconds"] = round(time.perf_counter()-start,5)
    result["matmul_finite"] = bool(torch.isfinite(c).all().item())
    if not result["matmul_finite"]:
        raise RuntimeError("nonfinite matrix result")
    # Representative convolution used in visual models.
    conv = torch.nn.Conv2d(3,16,3,padding=1).to("cuda",dtype=torch.float16)
    x = torch.randn((1,3,128,128),device="cuda",dtype=torch.float16)
    y=conv(x)
    torch.cuda.synchronize()
    result["conv_shape"] = list(y.shape)
    result["conv_finite"] = bool(torch.isfinite(y).all().item())
    if not result["conv_finite"]:
        raise RuntimeError("nonfinite convolution")
    result["peak_allocated_bytes"] = int(torch.cuda.max_memory_allocated())
    del x,y,conv,a,b,c
    torch.cuda.empty_cache()
    torch.cuda.synchronize()
    result["status"] = "PASS"
    return result


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--output",type=Path,required=True)
    args=p.parse_args()
    if args.output.exists():raise FileExistsError("immutable output exists")
    result=run()
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.open("x") as f:
        json.dump(result,f,indent=2,sort_keys=True); f.write("\n")
    print("VISION_GPU_SMOKE=PASS",json.dumps(result),flush=True)


if __name__=="__main__":
    main()
