#!/usr/bin/python3
"""Conservative, bounded RTX 5060 Ti inference stability pilot.
Only actions: local Ollama BGE-M3 embedding and stop that same model.
No PCI writes, GRUB changes, CUDA toolkit installs, service changes or reboot.
"""
import argparse
import csv
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
import time
from urllib import request, error

EXPECTED_BOOT="067e4fa7-1585-4f81-86fd-30cd6cc4e6ea"
GPU="0000:03:00.0"
BRIDGE="0000:02:00.0"
MODEL="bge-m3:latest"
LOCAL="http://127.0.0.1:11434"
GATEWAY="http://127.0.0.1:11435"
BASE=Path(__file__).resolve().parent
GPU_FIELDS=("temperature.gpu","power.draw","utilization.gpu","memory.used",
            "memory.total","pcie.link.gen.current","pcie.link.width.current")
XID_PATTERN=re.compile(r"NVRM:\s*Xid|GPU has fallen off the bus|PCIe Bus Error|AER:.*(?:error|received)",re.I)
START_TIME=time.monotonic()
MAX_TEMP=73.0  # deliberately conservative relative to NVIDIA thermal limits
MAX_POWER=155.0 # below observed 180W power limit
POWER_TELEM_TIMEOUT=4.0
MODEL_MIB_THRESHOLD=128

def stop_if(notok, reason):
    if notok: raise RuntimeError(reason)

def run(cmd,timeout=5):
    p=subprocess.run(cmd,capture_output=True,text=True,timeout=timeout)
    stop_if(p.returncode!=0,"command failed: %s (%s)" %(cmd[0],p.stderr[-200:]))
    return p.stdout.strip()

def api(url, data=None, timeout=5):
    payload=json.dumps(data).encode() if data is not None else None
    headers={"Content-Type":"application/json"} if payload is not None else {}
    req=request.Request(url,data=payload,headers=headers)
    with request.urlopen(req,timeout=timeout) as response:
        return json.loads(response.read())

def boot():return Path("/proc/sys/kernel/random/boot_id").read_text().strip()

def aer():
    result={}
    for b in (BRIDGE,GPU):
        p=Path("/sys/bus/pci/devices")/b
        stop_if(not p.is_dir(),"GPU/bridge missing: "+b)
        stop_if((p/"current_link_speed").read_text().strip()!="8.0 GT/s PCIe" or
                (p/"current_link_width").read_text().strip()!="4",
                "Gen3 x4 link drift: "+b)
        counts=[]
        for f in ("aer_dev_correctable","aer_dev_nonfatal","aer_dev_fatal"):
            totals=[int(l.split()[-1]) for l in (p/f).read_text().splitlines()
                    if l.startswith("TOTAL_")]
            stop_if(len(totals)!=1,"missing AER counter: "+b)
            counts.extend(totals)
        stop_if(any(counts),"nonzero AER: %s %s"%(b,counts))
        result[b]=counts
    return result

def gpu_sample():
    vals=next(csv.reader([run(["/usr/bin/nvidia-smi","--query-gpu="+",".join(GPU_FIELDS),
                         "--format=csv,noheader,nounits"],timeout=POWER_TELEM_TIMEOUT)]))
    stop_if(len(vals)!=len(GPU_FIELDS),"incomplete NVIDIA-SMI GPU fields")
    temp,power,util,mem,total,gen,width=map(float,vals)
    stop_if(gen!=3 or width!=4,"NVIDIA current PCIe no longer Gen3 x4")
    stop_if(temp>MAX_TEMP,"GPU temperature >%.0fC: %.1f"%(MAX_TEMP,temp))
    stop_if(power>MAX_POWER,"GPU power >%.0fW: %.1f"%(MAX_POWER,power))
    stop_if(mem>8000,"unplanned >8GiB VRAM occupancy: %.0f"%(mem))
    return dict(t=time.monotonic()-START_TIME,temp_c=temp,power_w=power,
                util_pct=util,mem_mib=mem,link_gen=gen,link_width=width)

def kernel_errors():
    raw=run(["/usr/bin/journalctl","-k","-b","--no-pager","-o","cat"],timeout=8)
    return [l[-350:] for l in raw.splitlines() if XID_PATTERN.search(l)]

def preflight():
    stop_if(boot()!=EXPECTED_BOOT,"unexpected boot")
    stop_if(run(["/usr/bin/systemctl","is-active","ai-egpu-gen3-ha.service"])!="active",
            "Gen3 + HA boot gate not active")
    stop_if(run(["/usr/bin/systemctl","is-active","ollama.service"])!="active",
            "Ollama inactive")
    stop_if(Path("/sys/bus/pci/devices/"+GPU+"/driver").resolve().name!="nvidia",
            "RTX not bound to NVIDIA driver")
    stop_if(kernel_errors(),"kernel Xid/AER before test")
    aer()
    health=api(GATEWAY+"/health",timeout=5)
    rm=health.get("resource_manager",{})
    sch=health.get("scheduler",{})
    stop_if(health.get("status")!="ok" or
            rm.get("state")!="IDLE" or
            sch.get("active_count",0)!=0 or sch.get("queued_count",0)!=0 or
            sch.get("admission_blocked") is not False or
            health.get("gpu_residency",{}).get("recovery_required") is not False,
            "resource manager not idle/safe; abort")
    models=api(LOCAL+"/api/ps",timeout=5).get("models",[])
    stop_if(models,"Ollama already holds a model, refuse to interrupt user workload")
    baseline=gpu_sample()
    stop_if(baseline["mem_mib"]>256,
            "RTX unexpectedly occupied before test")
    return baseline

def docs():
    sources=[
        Path("/srv/ai-data/staging/egpu-gen3-ha-bootfix-20261023/README.md"),
        Path("/srv/ai-data/staging/egpu-gen3-ha-bootfix-20261023/REPORT.md"),
        Path("/srv/ai-data/staging/egpu-gen3-ha-persist-20261023/README.md"),
    ]
    texts=[]
    for p in sources:
        text=p.read_text(encoding="utf-8")
        stop_if(len(text)<800,"technical source unexpectedly short "+str(p))
        texts.append(text)
    return texts

def make_inputs(source, count):
    result=[]
    for i in range(count):
        t=source[i%len(source)]
        offset=((i//len(source))*370) % max(1,len(t)-1000)
        segment=t[offset:offset+1450]
        if len(segment)<600:segment=t[:1450]
        result.append(segment)
    return result

def stop_model():
    # Explicitly stop only the BGE-M3 model that did not exist at preflight.
    try:
        r=subprocess.run(["/usr/local/bin/ollama","stop",MODEL],
                         capture_output=True,text=True,timeout=12)
        return dict(rc=r.returncode,stdout=r.stdout.strip()[-250:],
                    stderr=r.stderr.strip()[-250:])
    except Exception as e:return dict(error=repr(e))

def loop_samples(log, stop_event, stopped_for_error):
    while not stop_event.is_set():
        try:
            stop_if(boot()!=EXPECTED_BOOT,"host boot changed")
            rec=gpu_sample()
            aer()
            log.append(rec)
        except Exception as e:
            stopped_for_error.append(str(e))
            stop_event.set()
            break
        stop_event.wait(0.75)

def write_report(result,phase):
    target=BASE/("result-"+phase+".json")
    target.write_text(json.dumps(result,ensure_ascii=False,indent=2,sort_keys=True)+"\n")
    print("REPORT_FILE="+str(target),flush=True)

def main(phase):
    stop_if(phase not in ("smoke","sustained"),"invalid phase")
    info={"phase":phase,"boot_id":boot(),"model":MODEL,
          "stage":"init","status":"NOT_STARTED",
          "test_started_at":datetime.now(timezone.utc).isoformat()}
    samples=[]
    errs=[]
    stop_event=threading.Event()
    watcher=None
    issued=False
    try:
        baseline=preflight()
        info["baseline"]=baseline
        info["stage"]="compute"
        print("PREFLIGHT_PASS boot=%s memory=%.0fMiB temp=%.0fC PCIe=Gen3x4" %
              (info["boot_id"],baseline["mem_mib"],baseline["temp_c"]),flush=True)
        watcher=threading.Thread(target=loop_samples,
                                 args=(samples,stop_event,errs),daemon=True)
        watcher.start()
        source=docs()
        loops=1 if phase=="smoke" else 6
        size=2 if phase=="smoke" else 3
        allowed=35 if phase=="smoke" else 72
        deadline=time.monotonic()+allowed
        embeds=0
        for i in range(loops):
            stop_if(stop_event.is_set(),"safety monitor stopped: "+str(errs))
            stop_if(time.monotonic()>deadline,"bounded inference time exceeded")
            stop_if(bool(kernel_errors()),"NVIDIA Xid/AER appeared")
            payload={"model":MODEL,"input":make_inputs(source,size),
                     "truncate":True,"keep_alive":"2m"}
            issued=True
            resp=api(LOCAL+"/api/embed",payload,timeout=min(35,max(8,deadline-time.monotonic())))
            out=resp.get("embeddings",[])
            stop_if(len(out)!=size or not all(isinstance(x,list) and len(x)>500 for x in out),
                    "invalid embedding result or incomplete output")
            embeds+=len(out)
            if i in (0,loops//2,loops-1):
                print("COMPUTE_STEP=%d/%d embeddings=%d" % (i+1,loops,embeds),flush=True)
        stop_if(stop_event.is_set(),"safety monitor stopped: "+str(errs))
        stop_if(bool(kernel_errors()),"kernel errors during compute")
        aer()
        if samples:
            peak_mem=max(s["mem_mib"] for s in samples)
            peak_power=max(s["power_w"] for s in samples)
            peak_temp=max(s["temp_c"] for s in samples)
            peak_util=max(s["util_pct"] for s in samples)
        else:peak_mem=peak_power=peak_temp=peak_util=0
        info.update(embeddings_generated=embeds,iterations=loops,documents_per_request=size,
                    max_temp_c=peak_temp,max_power_w=peak_power,
                    max_util_pct=peak_util,max_mem_mib=peak_mem,
                    gpu_memory_delta_mib=peak_mem-baseline["mem_mib"],
                    sample_count=len(samples))
        stop_if(peak_mem-baseline["mem_mib"]<MODEL_MIB_THRESHOLD,
                "NOT_VERIFIED: model may have run on iGPU/CPU (NVIDIA VRAM did not grow)")
        stop_if(peak_util<=0 and peak_power-baseline["power_w"]<6,
                "NOT_VERIFIED: NVIDIA compute/power activity not observed")
        info["status"]="GPU_COMPUTE_PASS"
        print("GPU_COMPUTE_PASS peak_mem=%.0fMiB peak_util=%.0f%% peak_power=%.1fW max_temp=%.1fC"%
              (peak_mem,peak_util,peak_power,peak_temp),flush=True)
    except Exception as e:
        info["status"]="BLOCKED"
        info["reason"]=repr(e)
        print("ABORT="+repr(e),flush=True)
    finally:
        stop_event.set()
        if watcher: watcher.join(timeout=4)
        info["safety_monitor_errors"]=errs
        info["sample_count"]=len(samples)
        if samples:
            info["max_temp_c"]=max(s["temp_c"] for s in samples)
            info["max_power_w"]=max(s["power_w"] for s in samples)
            info["max_util_pct"]=max(s["util_pct"] for s in samples)
            info["max_mem_mib"]=max(s["mem_mib"] for s in samples)
        if issued:info["model_stop"]=stop_model()
        try:
            # Ollama's stop replies before CUDA memory is necessarily reclaimed.
            # Poll read-only for bounded time instead of reporting a false leak.
            release_start=time.monotonic()
            for _ in range(18):
                stop_if(boot()!=EXPECTED_BOOT,"unexpected boot during model unload")
                info["final_gpu"]=gpu_sample()
                info["final_aer"]=aer()
                info["final_models"]=api(LOCAL+"/api/ps",timeout=4).get("models",[])
                if not info["final_models"] and info["final_gpu"]["mem_mib"]<=256:
                    break
                time.sleep(0.8)
            info["memory_release_wait_s"]=round(time.monotonic()-release_start,2)
            info["final_kernel_errors"]=kernel_errors()
            if info["final_kernel_errors"] or info["final_models"]:
                info["status"]="BLOCKED"
                info["final_warning"]="GPU error or model not unloaded"
            if info["status"]=="GPU_COMPUTE_PASS":
                if info["safety_monitor_errors"]:
                    info["status"]="BLOCKED"
                    info["reason"]="safety monitor errors"
                elif info["final_gpu"]["mem_mib"]>256:
                    info["status"]="BLOCKED"
                    info["reason"]="CUDA model still occupies RTX VRAM after bounded cleanup wait"
        except Exception as e:
            info["status"]="BLOCKED"
            info["post_test_diagnostic_error"]=repr(e)
        info["test_finished_at"]=datetime.now(timezone.utc).isoformat()
        info["samples"]=samples
        write_report(info,phase)
        print("FINAL="+info["status"],flush=True)
    return 0 if info["status"]=="GPU_COMPUTE_PASS" else 2

if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("phase",choices=("smoke","sustained"))
    args=parser.parse_args()
    raise SystemExit(main(args.phase))
