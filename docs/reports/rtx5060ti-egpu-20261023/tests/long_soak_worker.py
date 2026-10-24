#!/usr/bin/python3
"""Single-run, supervised long cuBLAS SGEMM workload. No service changes."""
import argparse
import ctypes
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import signal
import sys
import time
import extreme_probe as old

PHASES = [("warmup", 2048, 300.0), ("ramp", 4096, 120.0),
          ("sustain", 8192, 7200.0)]
STOP = False

def stamp():
    return datetime.now(timezone.utc).isoformat()

def stop_requested(signum, _frame):
    global STOP
    STOP = True

def save_atomic(path, record):
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w") as fh:
        json.dump(record, fh, sort_keys=True, ensure_ascii=False)
        fh.write("\n")
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(temporary, path)

def parent_death_guard(expected_parent):
    # On Linux, terminate CUDA load if the supervisor unexpectedly dies.
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(1, signal.SIGTERM, 0, 0, 0) != 0:
        raise RuntimeError("PR_SET_PDEATHSIG failed")
    if os.getppid() != expected_parent:
        raise RuntimeError("Supervisor disappeared before guard was installed")

def exercise(gpu, phase, n, seconds, state, path):
    old.require(not STOP, "termination requested")
    count = 0
    size = n*n*4
    a = gpu.alloc(size)
    b = gpu.alloc(size)
    c = gpu.alloc(size)
    gpu.fill(a, 0x3f, size)
    gpu.fill(b, 0x3f, size)
    gpu.fill(c, 0, size)
    gpu.sync()
    begin = time.monotonic()
    next_update = begin
    next_verify = begin + 90.0
    print("PHASE_BEGIN", phase, "N", n, "duration", seconds, flush=True)
    while True:
        old.require(not STOP, "supervisor/timeout requested termination")
        elapsed = time.monotonic() - begin
        if elapsed >= seconds:
            break
        gpu.gemm(n, a, b, c)
        count += 1
        state["completed_ops"] += 1
        now = time.monotonic()
        if now >= next_verify:
            gpu.verify_gemm(n, c)
            next_verify = now + 90.0
        if now >= next_update:
            state.update(stage=phase, stage_seconds=round(now-begin, 3),
                         stage_target_seconds=seconds, stage_ops=count,
                         last_heartbeat_monotonic=now, updated_utc=stamp())
            save_atomic(path, state)
            next_update = now + 2.0
    sample = gpu.verify_gemm(n, c)
    elapsed = time.monotonic() - begin
    # Release the phase buffers before allocating the next ones.
    for ptr in (c, b, a):
        gpu.check(gpu.r.cudaFree(ptr), "cudaFree/phase")
        gpu.buffers.remove(ptr)
    outcome = dict(stage=phase, matrix_n=n, requested_seconds=seconds,
                   compute_seconds=round(elapsed, 3), sgemm_ops=count,
                   numerical_check=round(sample, 6))
    state["stages"].append(outcome)
    state.update(stage=phase+"_DONE", stage_seconds=round(elapsed, 3),
                 stage_ops=count, updated_utc=stamp(),
                 last_heartbeat_monotonic=time.monotonic())
    save_atomic(path, state)
    print("PHASE_END", json.dumps(outcome), flush=True)

def run(folder, parent_pid):
    state_path = folder/"worker_state.json"
    result_path = folder/"worker_result.json"
    signal.signal(signal.SIGTERM, stop_requested)
    signal.signal(signal.SIGINT, stop_requested)
    state = dict(status="STARTING", pid=os.getpid(),
                 boot_id=old.BOOT_ID, updated_utc=stamp(),
                 completed_ops=0, stage="preflight", stage_seconds=0,
                 last_heartbeat_monotonic=time.monotonic(), stages=[])
    save_atomic(state_path, state)
    gpu = None
    errors = []
    result = dict(start_utc=stamp(), verdict="INCOMPLETE")
    try:
        parent_death_guard(parent_pid)
        result["baseline"] = old.preflight()
        old.require(not STOP, "stop requested during preflight")
        gpu = old.API(with_blas=True)
        gpu.blas_handle()
        state["status"] = "RUNNING"
        save_atomic(state_path, state)
        for phase,n,duration in PHASES:
            exercise(gpu,phase,n,duration,state,state_path)
        old.require(len(state["stages"])==3, "not all phases completed")
        old.require(state["stages"][-1]["compute_seconds"] >= 7200.0,
                    "sustain was shorter than two hours")
        result["verdict"] = "WORK_COMPLETE"
    except BaseException as e:
        result["error"] = repr(e)
        print("WORKER_ABORT", repr(e), flush=True)
    finally:
        if gpu:
            try:
                errors = gpu.close()
            except BaseException as e:
                errors = ["GPU cleanup raised "+repr(e)]
        result.update(end_utc=stamp(), stages=state["stages"],
                      completed_ops=state["completed_ops"],
                      cuda_cleanup_errors=errors)
        if errors:
            result["verdict"] = "INCOMPLETE"
        state.update(status="FINISHED", stage="ended", updated_utc=stamp(),
                     worker_verdict=result["verdict"],
                     last_heartbeat_monotonic=time.monotonic())
        save_atomic(state_path, state)
        save_atomic(result_path, result)
        print("WORKER_FINAL", result["verdict"], "SGEMM", result["completed_ops"], flush=True)
    return 0 if result["verdict"]=="WORK_COMPLETE" else 2

if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--output-dir",required=True)
    parser.add_argument("--parent-pid",required=True,type=int)
    args=parser.parse_args()
    sys.exit(run(Path(args.output_dir), args.parent_pid))
