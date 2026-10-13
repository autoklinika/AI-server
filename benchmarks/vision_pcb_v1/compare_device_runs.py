#!/usr/bin/env python3
"""Verify CPU vs ROCm WinCLIP image-score equivalence and runtime on identical cases."""
import argparse
import hashlib
import json
from pathlib import Path
from statistics import median,mean

def run(cpu,gpu):
    if cpu.get("device")!="cpu" or gpu.get("device")!="cuda":
        raise ValueError("requires cpu and gpu reports")
    for key in ("model","checkpoint_sha256","backbone","pretrained","prompt","preprocessing","n_images"):
        if cpu.get(key)!=gpu.get(key):
            raise ValueError(f"comparison metadata mismatch: {key}")
    ca=cpu.get("records",[])
    ga=gpu.get("records",[])
    if len(ca)<4 or len(ca)!=len(ga):
        raise ValueError("requires at least 4 identical cases")
    if [r["sample_id"] for r in ca] != [r["sample_id"] for r in ga]:
        raise ValueError("sample order differs")
    delta=[abs(x["score"]-y["score"]) for x,y in zip(ca,ga)]
    if any(not (0<=x["score"]<=1 and 0<=y["score"]<=1) for x,y in zip(ca,ga)):
        raise ValueError("out of bounds output")
    # First case includes kernel JIT/warmup; report it separately.
    c_times=[r["forward_seconds"] for r in ca[1:]]
    g_times=[r["forward_seconds"] for r in ga[1:]]
    cmed=median(c_times)
    gmed=median(g_times)
    result={
        "schema_version":1,"status":"REAL_CPU_GPU_COMPARISON",
        "samples":len(ca),
        "checkpoint_sha256":cpu["checkpoint_sha256"],
        "max_abs_score_delta":max(delta),
        "mean_abs_score_delta":mean(delta),
        "cpu_cold_first_s":ca[0]["forward_seconds"],
        "gpu_cold_first_s":ga[0]["forward_seconds"],
        "cpu_median_warm_s":cmed,
        "gpu_median_warm_s":gmed,
        "cpu_mean_warm_s":mean(c_times),
        "gpu_mean_warm_s":mean(g_times),
        "median_speedup":cmed/gmed,
        "cpu_total_wall_s":cpu["wall_seconds"],
        "gpu_total_wall_s":gpu["wall_seconds"],
        "gpu_peak_allocated_bytes":gpu.get("peak_gpu_allocated_bytes"),
        "score_delta_pass_1e4":max(delta)<=1e-4,
        "caveat":"This is a CPU-vs-GPU inference equivalence/speed test, not a defect-detection benchmark.",
    }
    return result

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--cpu",required=True,type=Path)
    p.add_argument("--gpu",required=True,type=Path)
    p.add_argument("--out",required=True,type=Path)
    a=p.parse_args()
    if a.out.exists():raise FileExistsError("immutable report")
    cpu=json.loads(a.cpu.read_text())
    gpu=json.loads(a.gpu.read_text())
    out=run(cpu,gpu)
    a.out.parent.mkdir(parents=True,exist_ok=True)
    a.out.write_text(json.dumps(out,indent=2,sort_keys=True)+"\n")
    print("COMPARISON=PASS",out)

if __name__=="__main__":main()
