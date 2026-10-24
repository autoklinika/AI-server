#!/usr/bin/python3
"""Supervised RTX 5060 Ti CUDA allocation / cuBLAS stress.

Each process permits ONE phase and exits. Native existing CUDA 13 libraries,
no installs, no PCIe writes, no driver reload, no power-limit changes.
Two phases intentionally separate: (1) ~90% physical VRAM; (2) 180W TGP approach.
"""
import argparse
import ctypes as C
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time
from urllib.request import urlopen

BOOT_ID="067e4fa7-1585-4f81-86fd-30cd6cc4e6ea"
G="0000:03:00.0"
B="0000:02:00.0"
U="/usr/local/lib/ollama/cuda_v13"
STAGING=Path(__file__).resolve().parent
GIB=1024*1024*1024
MIB=1024*1024
TEMP_CEILING=76.0
POWER_CEILING=181.0
SAFETY_FREE_MIB=1000
VRAM_ALLOC_TARGET_MIB=14592
GPU_REGEX=("NVRM: Xid","GPU has fallen off the bus","PCIe Bus Error","AER: ")

def require(ok,msg):
    if not ok: raise RuntimeError(msg)

def cmd(args,timeout=4,allow=(0,)):
    p=subprocess.run(args,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,timeout=timeout)
    require(p.returncode in allow,"command failed: "+args[0]+" "+p.stderr[-220:])
    return p.stdout.strip()

def kernel_errors():
    txt=cmd(["/usr/bin/journalctl","-k","-b","--no-pager","-o","cat"],timeout=7)
    bad=[]
    for line in txt.splitlines():
        if ("NVRM: Xid" in line or "GPU has fallen off the bus" in line or
            "PCIe Bus Error" in line or ("AER:" in line and ("error" in line.lower() or "received" in line.lower()))):
            bad.append(line[-330:])
    return bad

def aer():
    all_dev={}
    for bdf in ("0000:00:01.1","0000:01:00.0",B,G):
        p=Path("/sys/bus/pci/devices")/bdf
        require(p.is_dir(),"PCIe BDF missing "+bdf)
        totals={}
        for kind in ("correctable","nonfatal","fatal"):
            file=p/("aer_dev_"+kind)
            if not file.is_file():continue
            lines=[line for line in file.read_text().splitlines() if line.startswith("TOTAL_")]
            require(len(lines)==1,"AER unreadable "+str(file))
            totals[kind]=int(lines[0].split()[-1])
        require(totals and all(v==0 for v in totals.values()),
                "AER NONZERO "+bdf+" "+repr(totals))
        all_dev[bdf]=totals
    return all_dev

def links():
    out={}
    for bdf in (B,G):
        p=Path("/sys/bus/pci/devices")/bdf
        speed=(p/"current_link_speed").read_text().strip()
        width=(p/"current_link_width").read_text().strip()
        require(speed=="8.0 GT/s PCIe" and width=="4",
                "PCIe link drift: "+bdf+" "+speed+" x"+width)
        out[bdf]={"speed":speed,"width":width}
    return out

def smi():
    cols=("temperature.gpu","power.draw","utilization.gpu","memory.used",
          "memory.free","memory.total","pcie.link.gen.current",
          "pcie.link.width.current","clocks.sm")
    raw=cmd(["/usr/bin/nvidia-smi","--query-gpu="+",".join(cols),
             "--format=csv,noheader,nounits"],timeout=4)
    require(len(raw.splitlines())==1,"unexpected NVIDIA-SMI GPU rows")
    vals=[float(t.strip()) for t in raw.split(",")]
    require(len(vals)==len(cols),"invalid NVIDIA-SMI telemetry")
    rec=dict(zip(("temperature_c","power_w","util_pct","used_mib","free_mib",
                  "total_mib","pcie_gen","pcie_width","clock_sm_mhz"),vals))
    require(rec["pcie_gen"]==3 and rec["pcie_width"]==4,
            "NVIDIA-SMI PCIe link drift")
    require(rec["temperature_c"]<TEMP_CEILING,
            "GPU temperature exceeded %.0f C"%TEMP_CEILING)
    require(rec["power_w"]<POWER_CEILING,
            "GPU power exceeded %.0f W"%POWER_CEILING)
    return rec

def api(path):
    with urlopen("http://127.0.0.1:"+path,timeout=5) as r:
        return json.load(r)

def other_clients():
    raw=cmd(["/usr/bin/nvidia-smi","--query-compute-apps=pid,process_name",
             "--format=csv,noheader"],timeout=4)
    pids=[]
    for line in raw.splitlines():
        line=line.strip()
        if not line or line.startswith("No running") or line.startswith("N/A"):continue
        token=line.split(",")[0].strip()
        if token.isdigit():
            pids.append(int(token))
    require(all(pid==os.getpid() for pid in pids),
            "other CUDA client appeared: "+repr(pids))
    return pids

def preflight():
    require(Path("/proc/sys/kernel/random/boot_id").read_text().strip()==BOOT_ID,
            "boot changed from verified Gen3 HA startup")
    require(cmd(["/usr/bin/systemctl","is-active","ai-egpu-gen3-ha.service"])=="active",
            "GPU Gen3 HA gate inactive")
    require(cmd(["/usr/bin/systemctl","is-active","ssh.service"])=="active" and
            cmd(["/usr/bin/systemctl","is-active","NetworkManager.service"])=="active",
            "network/SSH not running")
    require(Path("/sys/bus/pci/devices/"+G+"/driver").resolve().name=="nvidia",
            "GPU NVIDIA driver unbound")
    links()
    aer()
    require(not kernel_errors(),"existing NVIDIA Xid/AER in this boot")
    r=api("11435/health")
    require(r.get("status")=="ok" and
            r.get("gpu_residency",{}).get("recovery_required") is False and
            r.get("resource_manager",{}).get("state")=="IDLE" and
            r.get("scheduler",{}).get("active_count")==0 and
            r.get("scheduler",{}).get("queued_count")==0,
            "RM is busy or requires recovery")
    require(api("11434/api/ps").get("models",[])==[],
            "Ollama model running, refuse to compete with active inference")
    require(not other_clients(),"other GPU computation active")
    first=smi()
    require(first["used_mib"]<=256,"CUDA device already occupied")
    require(first["total_mib"]>=16000 and first["free_mib"]>=15500,
            "unexpected VRAM size/occupancy")
    cap=cmd(["/usr/bin/nvidia-smi","--query-gpu=power.limit",
             "--format=csv,noheader,nounits"])
    require(abs(float(cap)-180.0)<0.1,"board not at expected factory 180W limit")
    return first

class API:
    def __init__(self,with_blas):
        self.r=C.CDLL(U+"/libcudart.so.13",mode=C.RTLD_GLOBAL)
        self.b=C.CDLL(U+"/libcublas.so.13",mode=C.RTLD_GLOBAL) if with_blas else None
        self.bind(self.r,"cudaSetDevice",[C.c_int])
        self.bind(self.r,"cudaMemGetInfo",[C.POINTER(C.c_size_t),C.POINTER(C.c_size_t)])
        self.bind(self.r,"cudaMalloc",[C.POINTER(C.c_void_p),C.c_size_t])
        self.bind(self.r,"cudaMemset",[C.c_void_p,C.c_int,C.c_size_t])
        self.bind(self.r,"cudaMemcpy",[C.c_void_p,C.c_void_p,C.c_size_t,C.c_int])
        self.bind(self.r,"cudaDeviceSynchronize",[])
        self.bind(self.r,"cudaFree",[C.c_void_p])
        self.bind(self.r,"cudaDeviceReset",[])
        if with_blas:
            self.bind(self.b,"cublasCreate_v2",[C.POINTER(C.c_void_p)])
            self.bind(self.b,"cublasDestroy_v2",[C.c_void_p])
            self.bind(self.b,"cublasSgemm_v2",
                [C.c_void_p,C.c_int,C.c_int,C.c_int,C.c_int,C.c_int,
                 C.POINTER(C.c_float),C.c_void_p,C.c_int,
                 C.c_void_p,C.c_int,C.POINTER(C.c_float),C.c_void_p,C.c_int])
        self.check(self.r.cudaSetDevice(0),"cudaSetDevice")
        self.buffers=[]
        self.handle=C.c_void_p()

    @staticmethod
    def bind(lib,name,types):
        f=getattr(lib,name); f.argtypes=types; f.restype=C.c_int

    def check(self,rc,name):
        require(rc==0,"%s CUDA/cuBLAS error code %s"%(name,rc))

    def alloc(self,bytes_):
        out=C.c_void_p()
        self.check(self.r.cudaMalloc(C.byref(out),bytes_),"cudaMalloc")
        require(bool(out.value),"CUDA malloc null")
        self.buffers.append(out)
        return out

    def fill(self,ptr,number,size):
        self.check(self.r.cudaMemset(ptr,number,size),"cudaMemset")

    def sync(self):
        self.check(self.r.cudaDeviceSynchronize(),"cudaDeviceSynchronize")

    def free_info(self):
        free,total=C.c_size_t(),C.c_size_t()
        self.check(self.r.cudaMemGetInfo(C.byref(free),C.byref(total)),"cudaMemGetInfo")
        return dict(free_mib=round(free.value/MIB,1),total_mib=round(total.value/MIB,1))

    def sample(self,ptr,offset,pattern):
        dst=(C.c_ubyte*64)()
        addr=C.c_void_p(ptr.value+offset)
        self.check(self.r.cudaMemcpy(C.cast(dst,C.c_void_p),addr,64,2),"cudaMemcpyDtoH")
        require(all(v==pattern for v in dst),"VRAM content verification failed")

    def blas_handle(self):
        self.check(self.b.cublasCreate_v2(C.byref(self.handle)),"cublasCreate")

    def gemm(self,N,A,B,D):
        alpha,beta=C.c_float(1.0),C.c_float(0.0)
        self.check(self.b.cublasSgemm_v2(
            self.handle,0,0,N,N,N,C.byref(alpha),A,N,B,N,C.byref(beta),D,N),"cublasSgemm")
        self.sync()

    def verify_gemm(self,N,D):
        target=C.c_float()
        self.check(self.r.cudaMemcpy(C.byref(target),D,4,2),"cudaMemcpyDtoH")
        # 0x3f repeated is positive nonzero float; expected ~0.557*N
        expected=C.c_float.from_buffer_copy(b"\x3f\x3f\x3f\x3f").value**2*N
        require(math.isfinite(target.value) and expected>0 and
                abs(target.value-expected)/expected<0.05,
                "cuBLAS numerical result invalid N=%d actual=%f expected=%f" %
                (N,target.value,expected))
        return target.value

    def close(self):
        errors=[]
        if self.handle.value:
            rc=self.b.cublasDestroy_v2(self.handle)
            if rc: errors.append("cublasDestroy error %s"%rc)
            self.handle=C.c_void_p()
        for ptr in self.buffers[::-1]:
            rc=self.r.cudaFree(ptr)
            if rc:errors.append("cudaFree error %s"%rc)
        self.buffers.clear()
        rc=self.r.cudaDeviceReset()
        if rc:errors.append("cudaDeviceReset error %s"%rc)
        return errors

class Watchdog:
    def __init__(self):
        self.samples=[]
        self.violations=[]
        self.sampling=threading.Event()
        self.time0=time.monotonic()
        self.thread=threading.Thread(target=self.run,daemon=True)
    def start(self): self.thread.start()
    def run(self):
        check_count=0
        while not self.sampling.is_set():
            try:
                require(Path("/proc/sys/kernel/random/boot_id").read_text().strip()==BOOT_ID,
                        "unexpected host reboot")
                record=smi()
                record["t"]=round(time.monotonic()-self.time0,2)
                links()
                aer()
                if check_count%3==0:
                    require(not kernel_errors(),"NVIDIA Xid/AER in kernel journal")
                    other_clients()
                self.samples.append(record)
            except Exception as e:
                self.violations.append(repr(e))
                self.sampling.set()
                return
            check_count+=1
            self.sampling.wait(0.7)
    def assert_ok(self):
        require(not self.sampling.is_set() and not self.violations,
                "watchdog stopped: "+repr(self.violations))
    def stop(self):
        self.sampling.set()
        self.thread.join(timeout=5)

def run_memory(gpu,watch):
    steps=[2048,4096,8192,12288,14336,14592]
    allocated=0
    allocation_entries=[]
    for step in steps:
        watch.assert_ok()
        need=step-allocated
        # Each block below 2 GiB for less fragmentation and transparent recovery.
        while need:
            amount=min(2048,need)
            stats=gpu.free_info()
            require(stats["free_mib"]-amount>=SAFETY_FREE_MIB,
                    "VRAM safety reserve below %d MiB"%SAFETY_FREE_MIB)
            ptr=gpu.alloc(amount*MIB)
            pattern=(0x30+len(allocation_entries)*17)%256
            gpu.fill(ptr,pattern,amount*MIB)
            gpu.sync()
            for offset in (0,(amount*MIB)//2,(amount*MIB)-64):
                gpu.sample(ptr,offset,pattern)
            allocation_entries.append((ptr,amount,pattern))
            allocated+=amount
            need-=amount
            watch.assert_ok()
        print("VRAM_STAGE %dMiB cudaFree=%sMiB"%(
            allocated,gpu.free_info()["free_mib"]),flush=True)
        # Wait long enough to capture NVIDIA-SMI occupancy after each step.
        end=time.monotonic()+1.4
        while time.monotonic()<end:
            watch.assert_ok()
            time.sleep(.12)
    require(allocated==VRAM_ALLOC_TARGET_MIB,"VRAM allocated amount differs from target")
    gpu.sync()
    # Revalidate sampled contents at maximum residency.
    for ptr,amount,pattern in allocation_entries:
        for offset in (0,(amount*MIB)//2,(amount*MIB)-64):
            gpu.sample(ptr,offset,pattern)
    full=gpu.free_info()
    require(full["free_mib"]>=SAFETY_FREE_MIB,
            "VRAM reserve was breached")
    at_end=time.monotonic()+5.0
    while time.monotonic()<at_end:
        watch.assert_ok()
        time.sleep(.2)
    return dict(allocated_mib=allocated,full_residency_free_mib=full["free_mib"],
                sample_checks_per_allocation=6,
                chunks=len(allocation_entries))

def run_power(gpu,watch):
    gpu.blas_handle()
    stages=[(1024,3.0),(2048,5.0),(4096,7.0),(6144,12.0),(8192,22.0)]
    peak_stage=[]
    total_ops=0
    for n,seconds in stages:
        watch.assert_ok()
        buffer_bytes=n*n*4
        a=gpu.alloc(buffer_bytes);b=gpu.alloc(buffer_bytes);out=gpu.alloc(buffer_bytes)
        gpu.fill(a,0x3f,buffer_bytes)
        gpu.fill(b,0x3f,buffer_bytes)
        gpu.fill(out,0,buffer_bytes)
        gpu.sync()
        start=time.monotonic()
        count=0
        while time.monotonic()-start<seconds:
            watch.assert_ok()
            gpu.gemm(n,a,b,out)
            count+=1
            total_ops+=1
        sample=gpu.verify_gemm(n,out)
        elapsed=round(time.monotonic()-start,2)
        # Always release stage allocations to prevent accumulating over 3GiB.
        for ptr in (out,b,a):
            gpu.check(gpu.r.cudaFree(ptr),"cudaFree/stage")
            gpu.buffers.remove(ptr)
        watch.assert_ok()
        peak=max((x["power_w"] for x in watch.samples),default=0)
        print("POWER_STAGE N=%d gemms=%d duration=%.1fs peak_smi=%.1fW"%
              (n,count,elapsed,peak),flush=True)
        peak_stage.append(dict(n=n,completed_sgemm=count,elapsed_s=elapsed,
                               gemm_result=round(sample,3),max_power_so_far_w=peak))
        # If ≥175W already reached, avoid additional stress stage.
        if peak>=175.0:break
    return dict(stages=peak_stage,sgemm_total=total_ops,
                board_power_limit_w=180.0,
                target_near_cap_w=165.0)

def main(phase):
    report=dict(phase=phase,boot_id=BOOT_ID,status="NOT_STARTED",
                start=datetime.now(timezone.utc).isoformat())
    gpu=None;watch=None
    try:
        report["baseline"]=preflight()
        gpu=API(with_blas=phase=="power")
        watch=Watchdog()
        watch.start()
        watch.assert_ok()
        report["cuda_start_free"]=gpu.free_info()
        if phase=="memory":
            report["work"]=run_memory(gpu,watch)
        else:
            report["work"]=run_power(gpu,watch)
        watch.assert_ok()
        require(not kernel_errors(),"kernel GPU errors after stage")
        report["precleanup_aer"]=aer()
        mx=max((x["used_mib"] for x in watch.samples),default=0.0)
        peakw=max((x["power_w"] for x in watch.samples),default=0.0)
        report["max_used_mib"]=mx
        report["max_used_percent"]=round(100*mx/report["baseline"]["total_mib"],2)
        report["peak_power_w"]=peakw
        report["peak_power_fraction"]=round(peakw/180.0,3)
        report["max_temp_c"]=max((x["temperature_c"] for x in watch.samples),default=None)
        report["max_util_pct"]=max((x["util_pct"] for x in watch.samples),default=None)
        if phase=="memory":
            require(report["max_used_percent"]>=89.0,
                    "VRAM occupancy not high enough to confirm high usage")
            report["status"]="HIGH_VRAM_PASS"
        else:
            report["status"]="NEAR_POWER_PASS" if peakw>=165.0 else "POWER_LOAD_PASS_TARGET_NOT_REACHED"
    except Exception as e:
        report["status"]="BLOCKED"
        report["error"]=repr(e)
        print("ABORT="+repr(e),flush=True)
    finally:
        if watch:
            watch.stop()
            report["samples"]=watch.samples
            report["watchdog_violations"]=watch.violations
            if watch.violations:
                report["status"]="BLOCKED"
        if gpu:
            try:
                report["cuda_cleanup_errors"]=gpu.close()
                if report["cuda_cleanup_errors"]:
                    report["status"]="BLOCKED"
            except Exception as e:
                report["status"]="BLOCKED"
                report["cuda_cleanup_exception"]=repr(e)
        try:
            report["post_driver"]=smi()
            report["post_kernel_errors"]=kernel_errors()
            report["post_aer"]=aer()
            report["post_links"]=links()
            if report["post_kernel_errors"]:
                report["status"]="BLOCKED"
            if report["post_driver"]["used_mib"]>256:
                report["status"]="BLOCKED"
                report["cleanup_note"]="CUDA device context still charged after reset; independent check needed"
        except Exception as e:
            report["status"]="BLOCKED"
            report["post_check_exception"]=repr(e)
        report["end"]=datetime.now(timezone.utc).isoformat()
        target=STAGING/("result-extreme-"+phase+".json")
        target.write_text(json.dumps(report,indent=2,sort_keys=True,ensure_ascii=False)+"\n")
        print("RESULT_FILE="+str(target),flush=True)
        summary={k:v for k,v in report.items() if k not in ("samples","precleanup_aer","post_aer","post_links","post_driver")}
        print("SUMMARY="+json.dumps(summary,ensure_ascii=False,sort_keys=True)[:2500],flush=True)
        print("FINAL="+report["status"],flush=True)
    return 0 if report["status"] in ("HIGH_VRAM_PASS","NEAR_POWER_PASS",
                                     "POWER_LOAD_PASS_TARGET_NOT_REACHED") else 2

if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("phase",choices=("memory","power"))
    options=parser.parse_args()
    raise SystemExit(main(options.phase))
