#!/usr/bin/python3
"""One-shot fail-closed eGPU soak supervisor, no persistent service/daemon."""
import argparse
import csv
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import signal
import statistics
import subprocess
import sys
import time
from urllib.request import urlopen
import extreme_probe as old

BASE = Path(__file__).resolve().parent
MAX_WALL_S = 7800                 # 2h warm+ramp+sustain plus 3 min cleanup
TEMP_STOP_C = 76.0
POWER_STOP_W = 181.0              # card hardware power limit remains 180 W
COLS = ("temperature.gpu", "power.draw", "utilization.gpu", "memory.used",
        "memory.free", "clocks.sm", "clocks.mem", "pstate",
        "pcie.link.gen.current", "pcie.link.width.current",
        "clocks_event_reasons.active", "clocks_event_reasons.sw_power_cap",
        "clocks_event_reasons.hw_thermal_slowdown",
        "clocks_event_reasons.sw_thermal_slowdown")
FIELDS = ("utc", "elapsed_s", "stage", "stage_elapsed_s", "completed_ops",
          "temp_c", "power_w", "gpu_util_pct", "used_mib", "free_mib",
          "sm_mhz", "mem_mhz", "pstate", "pcie_gen", "pcie_width",
          "clock_event_mask", "sw_power_cap", "hw_thermal", "sw_thermal")
STOP_REASON = None

def stamp():
    return datetime.now(timezone.utc).isoformat()

def atomic_json(path, obj):
    tmp=path.with_suffix(path.suffix+".tmp")
    with tmp.open("w") as f:
        json.dump(obj,f,indent=2,sort_keys=True,ensure_ascii=False)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp,path)

def read_json(path):
    try:
        with path.open("r") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}

def record_event(eventfile, event, **details):
    obj=dict(utc=stamp(), event=event, **details)
    with eventfile.open("a") as f:
        f.write(json.dumps(obj,sort_keys=True,ensure_ascii=False)+"\n")
        f.flush()
        os.fsync(f.fileno())
    print("EVENT",json.dumps(obj,ensure_ascii=False),flush=True)

def sample_gpu():
    raw=old.cmd(["/usr/bin/nvidia-smi","--query-gpu="+",".join(COLS),
                 "--format=csv,noheader,nounits"],timeout=5)
    old.require(len(raw.splitlines())==1,"missing/extra NVIDIA-SMI devices")
    cells=[v.strip() for v in raw.split(",")]
    old.require(len(cells)==len(COLS),"NVIDIA-SMI fields changed: "+raw[:220])
    def num(i): return float(cells[i])
    row=dict(temp_c=num(0),power_w=num(1),gpu_util_pct=num(2),
             used_mib=num(3),free_mib=num(4),sm_mhz=num(5),mem_mhz=num(6),
             pstate=cells[7],pcie_gen=int(cells[8]),pcie_width=int(cells[9]),
             clock_event_mask=cells[10],sw_power_cap=cells[11],
             hw_thermal=cells[12],sw_thermal=cells[13])
    validate_sample(row)
    return row

def validate_sample(row):
    old.require(row["pcie_gen"]==3 and row["pcie_width"]==4,
                "PCIe Gen3x4 changed in NVIDIA-SMI")
    old.require(row["temp_c"]<TEMP_STOP_C,
                "GPU >= 76C: %.1fC"%row["temp_c"])
    old.require(row["power_w"]<=POWER_STOP_W,
                "reported GPU power >181W: %.2fW"%row["power_w"])
    old.require(row["hw_thermal"]=="Not Active" and row["sw_thermal"]=="Not Active",
                "GPU thermal throttling detected")
    old.require(row["used_mib"]<4096,
                "unexpected VRAM occupancy >4GiB (concurrent workload?)")
    old.require(0<=row["gpu_util_pct"]<=100,"invalid SM/GPU utilization")

def check_rm():
    with urlopen("http://127.0.0.1:11435/health",timeout=4) as h:
        data=json.load(h)
    rm=data.get("resource_manager",{})
    gpu=data.get("gpu_residency",{})
    scheduler=data.get("scheduler",{})
    old.require(data.get("status")=="ok" and rm.get("state")=="IDLE" and
                gpu.get("recovery_required") is False and
                scheduler.get("active_count")==0 and
                scheduler.get("queued_count")==0,
                "RM active/unhealthy or recovery required: "+
                json.dumps({"rm":rm.get("state"),"residency":gpu,
                            "active":scheduler.get("active_count"),
                            "queued":scheduler.get("queued_count")}))
    with urlopen("http://127.0.0.1:11434/api/ps",timeout=4) as h:
        models=json.load(h).get("models",[])
    old.require(not models,"Ollama model appeared while stress active")

def check_clients(worker_pid):
    raw=old.cmd(["/usr/bin/nvidia-smi","--query-compute-apps=pid,process_name",
                 "--format=csv,noheader"],timeout=4)
    pids=[]
    for line in raw.splitlines():
        first=line.strip().split(",")[0].strip()
        if first.isdigit():
            pids.append(int(first))
    old.require(all(p==worker_pid for p in pids),
                "unexpected GPU compute process: "+repr(pids))

def check_safety(row,worker_pid,elapsed,worker_state,start):
    old.require(Path("/proc/sys/kernel/random/boot_id").read_text().strip()==old.BOOT_ID,
                "unexpected reboot: boot id changed")
    old.links()      # verifies bridge + GPU are still 8 GT/s x4
    old.aer()        # verifies root, upstream, downstream, GPU: ALL zero
    if elapsed > 40:
        old.require(bool(worker_state),"worker heartbeat missing >40s")
    if worker_state and worker_state.get("status") != "FINISHED":
        age=time.monotonic()-worker_state.get("last_heartbeat_monotonic",start)
        old.require(age<25.0,"worker heartbeat stale %.1fs"%age)
    if int(elapsed)//5 != int(max(0.0,elapsed-1))//5:
        # No need to reread the whole journal and gateway every second.
        errs=old.kernel_errors()
        old.require(not errs,"NVIDIA Xid / PCIe AER journal: "+repr(errs[-4:]))
        check_clients(worker_pid)
        check_rm()

def terminate_child(child):
    if child is None or child.poll() is not None:
        return
    child.terminate()
    try:
        child.wait(timeout=9)
    except subprocess.TimeoutExpired:
        child.kill()
        child.wait(timeout=4)

def on_term(signum, frame):
    global STOP_REASON
    STOP_REASON="signal "+str(signum)+" received"

def report_markdown(data):
    stat=data.get("sustain_statistics",{})
    phase=data.get("stage_statistics",{})
    err=data.get("error")
    def display(value): return "N/A" if value is None else str(value)
    text=[
        "# RTX 5060 Ti / TBGAA — Long SGEMM stability soak",
        "",
        "**Verdict:** "+data["verdict"],
        "**Reason:** "+display(err),
        "**Started UTC:** "+data["start_utc"],
        "**Finished UTC:** "+data["finish_utc"],
        "**Boot ID:** "+old.BOOT_ID,
        "",
        "## Workload and acceptance",
        "Warmup 300 s at SGEMM 2048²; ramp 120 s at SGEMM 4096²; ",
        "sustained 7200 s at SGEMM 8192². No simultaneous high-VRAM load.",
        "Factory board limit 180 W unchanged, stop at >=76°C / >181 W.",
        "One supervised CUDA worker, no auto-restart, hardware/driver untouched.",
        "",
        "- Sustained compute duration (s): "+display(data.get("sustain_compute_s")),
        "- Total SGEMM operations: "+display(data.get("completed_sgemm_ops")),
        "- Sustained samples (around 1 Hz): "+display(stat.get("samples")),
        "- Mean sustained power (W): "+display(stat.get("mean_power_w")),
        "- Peak sustained power (W): "+display(stat.get("max_power_w")),
        "- Mean sustained temperature (°C): "+display(stat.get("mean_temp_c")),
        "- Peak sustained temperature (°C): "+display(stat.get("max_temp_c")),
        "- Mean sustained utilization (%): "+display(stat.get("mean_util_pct")),
        "- Peak sustained utilization (%): "+display(stat.get("max_util_pct")),
        "- Peak sustained VRAM (MiB): "+display(stat.get("max_vram_mib")),
        "- Hardware/software thermal throttle samples: "+display(stat.get("thermal_throttle_samples")),
        "- SW power cap samples (normal at high load): "+display(stat.get("sw_power_cap_samples")),
        "- Gen3 x4 maintained (each telemetry sample + sysfs checks): "+display(data.get("pcie_link_stable")),
        "- Xid / AER: "+display(data.get("xid_aer_assessment")),
        "- Post CUDA cleanup/idle (P8): "+display(data.get("post_idle")),
        "- Post RM status: "+display(data.get("post_rm")),
        "",
        "## Warmup / clock behavior",
    ]
    for k,v in phase.items():
        text.append("- "+k+": "+json.dumps(v,ensure_ascii=False,sort_keys=True))
    text.extend(["","## Worker stages"])
    for stage in data.get("worker_stages",[]):
        text.append("- "+json.dumps(stage,ensure_ascii=False))
    text.extend(["","## Evidence / caveats",
                 "- telemetry.csv: direct NVIDIA-SMI ~1s samples, flushed/fsync to NVMe",
                 "- events.jsonl: faults, phase changes, start/stop and watchdog decisions",
                 "- worker_state.json, worker_result.json, worker.log: CUDA heartbeat/work evidence",
                 "- result-long-soak.json: this verdict's structured data",
                 "- launcher.log: detached one-shot process output",
                 "- No reboot, driver reload, PCIe writes or power-limit changes.",
                 "- A passing test is a finite stability observation, not a lifetime guarantee.",
                 "- AER and Xid are monitored in the active boot; power is as reported by NVIDIA-SMI.",
                 ""])
    return "\n".join(text)

def stats(samples):
    if not samples: return {"samples":0}
    def ss(key,prefix):
        vals=[float(r[key]) for r in samples]
        return {"mean_"+prefix:round(statistics.fmean(vals),2),
                "max_"+prefix:round(max(vals),2),
                "min_"+prefix:round(min(vals),2)}
    out=dict(samples=len(samples))
    for key,prefix in (("power_w","power_w"),("temp_c","temp_c"),
                       ("gpu_util_pct","util_pct"),("sm_mhz","sm_mhz"),
                       ("mem_mhz","mem_mhz")):
        out.update(ss(key,prefix))
    out["max_vram_mib"]=round(max(float(r["used_mib"]) for r in samples),2)
    out["thermal_throttle_samples"]=sum(
        r["hw_thermal"]!="Not Active" or r["sw_thermal"]!="Not Active"
        for r in samples)
    out["sw_power_cap_samples"]=sum(r["sw_power_cap"]=="Active" for r in samples)
    return out

def main(folder):
    folder.mkdir(parents=False,exist_ok=True)
    old.require(not (folder/"events.jsonl").exists() and
                not (folder/"result-long-soak.json").exists(),
                "refuse rerun/overwrite of an existing stress test")
    eventfile=folder/"events.jsonl"
    statusfile=folder/"status.json"
    csvfile=folder/"telemetry.csv"
    workerfile=folder/"worker_state.json"
    outcome=dict(verdict="INCOMPLETE",start_utc=stamp(),boot_id=old.BOOT_ID,
                 output_dir=str(folder))
    child=None
    samples=[]
    current_stage=None
    begin=time.monotonic()
    signal.signal(signal.SIGTERM,on_term)
    signal.signal(signal.SIGINT,on_term)
    try:
        record_event(eventfile,"PREFLIGHT_BEGIN")
        outcome["baseline"]=old.preflight()
        check_rm()
        record_event(eventfile,"PREFLIGHT_PASS",baseline=outcome["baseline"])
        with (folder/"worker.log").open("w",buffering=1) as output:
            child=subprocess.Popen(
                [sys.executable,"-u",str(BASE/"long_soak_worker.py"),
                 "--output-dir",str(folder),"--parent-pid",str(os.getpid())],
                stdout=output,stderr=subprocess.STDOUT,cwd=str(BASE))
            outcome["worker_pid"]=child.pid
            record_event(eventfile,"WORKER_STARTED",pid=child.pid)
            with csvfile.open("w",newline="",buffering=1) as f:
                writer=csv.DictWriter(f,fieldnames=FIELDS,extrasaction="ignore")
                writer.writeheader()
                next_tick=time.monotonic()
                while child.poll() is None:
                    now=time.monotonic()
                    elapsed=now-begin
                    old.require(STOP_REASON is None,STOP_REASON or "unknown signal")
                    old.require(elapsed < MAX_WALL_S,
                                "hard wall-time safety limit reached")
                    row=sample_gpu()
                    state=read_json(workerfile)
                    row.update(utc=stamp(),elapsed_s=round(elapsed,3),
                               stage=state.get("stage","starting"),
                               stage_elapsed_s=state.get("stage_seconds",0),
                               completed_ops=state.get("completed_ops",0))
                    writer.writerow(row)
                    f.flush()
                    os.fsync(f.fileno())
                    samples.append(row)
                    if row["stage"] != current_stage:
                        current_stage=row["stage"]
                        record_event(eventfile,"STAGE",stage=current_stage)
                    check_safety(row,child.pid,elapsed,state,begin)
                    if len(samples)%5==1:
                        atomic_json(statusfile,{
                            "verdict":"RUNNING","utc":row["utc"],
                            "elapsed_s":row["elapsed_s"],"stage":row["stage"],
                            "stage_elapsed_s":row["stage_elapsed_s"],
                            "completed_ops":row["completed_ops"],
                            "temp_c":row["temp_c"],"power_w":row["power_w"],
                            "gpu_util_pct":row["gpu_util_pct"],"pcie":"Gen3x4",
                            "samples":len(samples),"worker_pid":child.pid,
                            "run_dir":str(folder)})
                    next_tick+=1.0
                    time.sleep(max(0.0,next_tick-time.monotonic()))
        outcome["worker_exitcode"]=child.returncode
        worker_result=read_json(folder/"worker_result.json")
        outcome["worker_stages"]=worker_result.get("stages",[])
        outcome["completed_sgemm_ops"]=worker_result.get("completed_ops")
        sustain=next((s for s in outcome["worker_stages"] if s.get("stage")=="sustain"),{})
        outcome["sustain_compute_s"]=sustain.get("compute_seconds")
        old.require(child.returncode==0 and worker_result.get("verdict")=="WORK_COMPLETE",
                    "worker failed or exited early: "+repr(worker_result.get("error")))
        old.require(outcome["sustain_compute_s"] is not None and
                    outcome["sustain_compute_s"]>=7200.0,
                    "continuous sustain duration below 7200s")
        # Worker has exited; no GPU context should remain.
        for i in range(60):
            idle=sample_gpu()
            if idle["used_mib"]<=256 and idle["gpu_util_pct"]==0 and idle["pstate"]=="P8":
                outcome["post_idle"]=idle
                break
            time.sleep(1)
        old.require("post_idle" in outcome,"GPU did not return to P8 / release VRAM in 60s")
        old.preflight()  # includes Xid, four AER paths, both links, RM and empty Ollama
        outcome["post_rm"]="IDLE / recovery_required=false / 0 jobs"
        outcome["verdict"]="PASS"
    except BaseException as e:
        outcome["error"]=repr(e)
        if any(k in str(e).lower() for k in ("xid","aer","pcie","driver","thermal",
                "temperature","reboot","power","stale","heartbeat","gpu",
                "link","nvidia","cuda","other","unexpected")):
            outcome["verdict"]="FAIL"
        else:
            outcome["verdict"]="INCOMPLETE"
        record_event(eventfile,"ABORT",reason=outcome["error"])
    finally:
        terminate_child(child)
        wr=read_json(folder/"worker_result.json")
        outcome.setdefault("worker_stages",wr.get("stages",[]))
        outcome.setdefault("completed_sgemm_ops",wr.get("completed_ops"))
        outcome["worker_exitcode"]=child.poll() if child else None
        sust=next((s for s in outcome["worker_stages"] if s.get("stage")=="sustain"),{})
        outcome.setdefault("sustain_compute_s",sust.get("compute_seconds"))
        outcome["finish_utc"]=stamp()
        outcome["sample_count"]=len(samples)
        only_sustain=[r for r in samples if r.get("stage")=="sustain"]
        outcome["sustain_statistics"]=stats(only_sustain)
        outcome["stage_statistics"]={
            key:stats([r for r in samples if r.get("stage")==key])
            for key in ("warmup","ramp","sustain")}
        outcome["pcie_link_stable"]="yes for logged samples" if samples else "not tested"
        outcome["xid_aer_assessment"]="no errors in completed polls" if outcome["verdict"]=="PASS" else "inspect events and kernel"
        if outcome["verdict"]!="PASS":
            try:
                outcome["post_idle"]=sample_gpu() if child is not None else None
                outcome["post_aer"]=old.aer()
                outcome["post_kernel_errors"]=old.kernel_errors()
                outcome["post_links"]=old.links()
            except Exception as e:
                outcome["postcheck_error"]=repr(e)
        atomic_json(folder/"result-long-soak.json",outcome)
        (folder/"REPORT_LONG_SOAK.md").write_text(report_markdown(outcome))
        atomic_json(statusfile,{"verdict":outcome["verdict"],
                               "utc":outcome["finish_utc"],"run_dir":str(folder),
                               "reason":outcome.get("error"),
                               "sustain_compute_s":outcome.get("sustain_compute_s"),
                               "completed_ops":outcome.get("completed_sgemm_ops"),
                               "sample_count":len(samples)})
        record_event(eventfile,"FINAL",verdict=outcome["verdict"],
                     sustain_s=outcome.get("sustain_compute_s"),
                     samples=len(samples))
        print("FINAL",outcome["verdict"],"RESULT_DIR",str(folder),flush=True)
    return 0 if outcome["verdict"]=="PASS" else 2

def selftest():
    baseline={"temp_c":40.0,"power_w":170.0,"gpu_util_pct":99,
              "used_mib":900,"pcie_gen":3,"pcie_width":4,
              "hw_thermal":"Not Active","sw_thermal":"Not Active"}
    validate_sample(baseline)
    cases=[
        ("temperature",{"temp_c":76}),
        ("power",{"power_w":182}),
        ("gen",{"pcie_gen":4}),
        ("width",{"pcie_width":2}),
        ("thermal",{"hw_thermal":"Active"}),
        ("VRAM",{"used_mib":5000})
    ]
    for name,change in cases:
        try:
            validate_sample(dict(baseline,**change))
        except RuntimeError:
            print("FAULT_INJECTION_PASS",name,flush=True)
        else:
            raise AssertionError("Safety test failed to reject "+name)
    sleeper=subprocess.Popen(["/usr/bin/sleep","60"])
    terminate_child(sleeper)
    old.require(sleeper.poll() is not None,"unable to terminate worker")
    old.preflight()
    check_rm()
    live=sample_gpu()
    old.links()
    old.aer()
    old.require(not old.kernel_errors(),"existing Xid/AER")
    print("SELFTEST_PASS: no GPU workload started; safe termination verified",live,flush=True)

if __name__=="__main__":
    ap=argparse.ArgumentParser()
    ap.add_argument("--self-test",action="store_true")
    ap.add_argument("--output-dir")
    options=ap.parse_args()
    if options.self_test:
        selftest()
    else:
        if not options.output_dir:
            ap.error("--output-dir required")
        sys.exit(main(Path(options.output_dir)))
