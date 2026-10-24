"""DEV-only, conservative GPU admission memory budget for two real Ollama runtimes.

Policy uses host MemAvailable and NVIDIA-SMI *physical* memory, NEVER the
synthetic Vulkan device limit. The model estimates are strict allowlists.
This admission fence is NOT a kernel-enforced VRAM cap or proof of OS isolation.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import subprocess
from typing import Callable, Mapping


class PhysicalGPUBudgetDenied(ValueError):
    """Refuse admission without any implicit CPU/device fallback."""


@dataclass(frozen=True)
class MemoryObservation:
    ram_total_mib: int
    ram_available_mib: int
    rtx_total_mib: int
    rtx_used_mib: int
    rtx_free_mib: int


@dataclass(frozen=True)
class DeviceBudget:
    max_pool_mib: int
    models_mib: Mapping[str, int]


@dataclass(frozen=True)
class PhysicalGPUBudget:
    host_reserve_mib: int
    rtx_reserve_mib: int
    pools: Mapping[str, DeviceBudget]

    @classmethod
    def from_json(cls, raw: str | None, model_routes: Mapping[str, str]) -> PhysicalGPUBudget:
        if not raw:
            raise PhysicalGPUBudgetDenied("GPU routing requires an explicit bounded RAM/VRAM policy")
        try:
            policy=json.loads(raw)
        except (TypeError, ValueError) as exc:
            raise PhysicalGPUBudgetDenied("invalid memory budget JSON") from exc
        if not isinstance(policy, dict) or set(policy) != {
            "host_reserve_mib", "rtx_reserve_mib", "pools"
        }:
            raise PhysicalGPUBudgetDenied("budget fields incomplete or unexpected")
        def positive(value, name):
            if type(value) is not int or value < 256 or value > 131072:
                raise PhysicalGPUBudgetDenied("invalid bounded memory parameter "+name)
            return value
        host=positive(policy["host_reserve_mib"], "host_reserve_mib")
        rtx=positive(policy["rtx_reserve_mib"], "rtx_reserve_mib")
        if host < 4096 or rtx < 1024:
            raise PhysicalGPUBudgetDenied("safe host or RTX reserve too small")
        pools=policy["pools"]
        if not isinstance(pools,dict) or set(pools) != {"amd","rtx"}:
            raise PhysicalGPUBudgetDenied("two GPU budgets required")
        verified={}
        for gpu in ("amd","rtx"):
            obj=pools[gpu]
            if not isinstance(obj,dict) or set(obj) != {"max_pool_mib","models_mib"}:
                raise PhysicalGPUBudgetDenied("invalid pool budget for "+gpu)
            cap=positive(obj["max_pool_mib"],gpu+" max_pool_mib")
            models=obj["models_mib"]
            if not isinstance(models,dict) or not models:
                raise PhysicalGPUBudgetDenied("per-model memory estimates mandatory")
            verified_models={}
            for model,needed in models.items():
                if not isinstance(model,str) or model_routes.get(model) != gpu:
                    raise PhysicalGPUBudgetDenied("budgeted model must map to same physical GPU")
                cost=positive(needed,model)
                if cost>cap:
                    raise PhysicalGPUBudgetDenied("model exceeds configured GPU pool")
                verified_models[model]=cost
            verified[gpu]=DeviceBudget(cap,verified_models)
        if set().union(*(v.models_mib for v in verified.values())) != set(model_routes):
            raise PhysicalGPUBudgetDenied("every routed model needs a memory cost estimate")
        return cls(host,rtx,verified)

    def evaluate(self, *, gpu: str, model: str, loaded: set[str],
                 metrics: MemoryObservation) -> dict[str, int | str]:
        if gpu not in self.pools:
            raise PhysicalGPUBudgetDenied("unrecognized physical GPU")
        pool=self.pools[gpu]
        if model not in pool.models_mib:
            raise PhysicalGPUBudgetDenied("model has no accepted memory cost")
        if any(x not in pool.models_mib for x in loaded):
            raise PhysicalGPUBudgetDenied("unrecognized model resident on selected GPU")
        if any(type(v) is not int or v < 0 for v in (
            metrics.ram_total_mib,metrics.ram_available_mib,
            metrics.rtx_total_mib,metrics.rtx_used_mib,metrics.rtx_free_mib
        )):
            raise PhysicalGPUBudgetDenied("incomplete/untrustworthy physical memory reading")
        if (metrics.ram_total_mib < metrics.ram_available_mib or
            metrics.rtx_total_mib < metrics.rtx_free_mib or
            metrics.rtx_total_mib < metrics.rtx_used_mib or
            metrics.rtx_used_mib + metrics.rtx_free_mib > metrics.rtx_total_mib+256):
            raise PhysicalGPUBudgetDenied("inconsistent physical memory accounting")
        if (metrics.ram_total_mib <= self.host_reserve_mib or
            metrics.ram_available_mib <= self.host_reserve_mib):
            raise PhysicalGPUBudgetDenied("host RAM reserve breached")
        total_estimated=sum(pool.models_mib[x] for x in loaded | {model})
        if total_estimated > pool.max_pool_mib:
            raise PhysicalGPUBudgetDenied("requested model exceeds shared physical-GPU pool budget")
        incremental=0 if model in loaded else pool.models_mib[model]
        if gpu=="amd":
            if total_estimated > metrics.ram_total_mib-self.host_reserve_mib:
                raise PhysicalGPUBudgetDenied("iGPU budget exceeds physically installed host RAM")
            if incremental > metrics.ram_available_mib-self.host_reserve_mib:
                raise PhysicalGPUBudgetDenied("host MemAvailable cannot cover new model")
        else:
            if (pool.max_pool_mib + self.rtx_reserve_mib >
                metrics.rtx_total_mib):
                raise PhysicalGPUBudgetDenied("RTX pool+reserve exceed physical VRAM")
            if metrics.rtx_used_mib > pool.max_pool_mib:
                raise PhysicalGPUBudgetDenied("RTX already exceeds safe occupancy cap")
            if incremental+self.rtx_reserve_mib > metrics.rtx_free_mib:
                raise PhysicalGPUBudgetDenied("RTX free VRAM below requested model+reserve")
        return {"gpu":gpu,"model":model,"estimated_pool_mib":total_estimated,
                "incremental_mib":incremental,
                "remaining_host_mib":metrics.ram_available_mib-self.host_reserve_mib}

    def snapshot(self):
        return {"host_reserve_mib":self.host_reserve_mib,
                "rtx_reserve_mib":self.rtx_reserve_mib,
                "pools":{k:{"max_pool_mib":v.max_pool_mib,
                            "models_mib":dict(v.models_mib)} for k,v in self.pools.items()},
                "physical_ram_source":"/proc/meminfo MemTotal/MemAvailable",
                "nvidia_vram_source":"nvidia-smi memory.total/used/free",
                "vulkan_memory_budget":"IGNORED_AS_UNTRUSTWORTHY",
                "hard_kernel_gpu_vram_enforcement":"NOT_AVAILABLE",
                "systemd_cgroup_memory_enforcement":"NOT_DEPLOYED"}


def read_physical_memory() -> MemoryObservation:
    """Read physical host RAM and one expected RTX; raise rather than guess."""
    mem={}
    try:
        for bdf,vendor,device in (
            ("0000:c6:00.0","0x1002","0x150e"),
            ("0000:03:00.0","0x10de","0x2d04"),
        ):
            root=Path("/sys/bus/pci/devices")/bdf
            if ((root/"vendor").read_text().strip()!=vendor or
                (root/"device").read_text().strip()!=device):
                raise PhysicalGPUBudgetDenied("physical GPU identity mismatch")
        for line in Path("/proc/meminfo").read_text().splitlines():
            key,_,value=line.partition(":")
            if key in ("MemTotal","MemAvailable"):
                pieces=value.split()
                if len(pieces)!=2 or pieces[1]!="kB":
                    raise PhysicalGPUBudgetDenied("unexpected /proc/meminfo units")
                mem[key]=int(pieces[0])//1024
        if set(mem)!={"MemTotal","MemAvailable"}:
            raise PhysicalGPUBudgetDenied("host RAM metrics unavailable")
        process=subprocess.run([
            "/usr/bin/nvidia-smi",
            "--query-gpu=memory.total,memory.used,memory.free",
            "--format=csv,noheader,nounits",
        ],capture_output=True,text=True,timeout=4,check=False)
        if process.returncode:
            raise PhysicalGPUBudgetDenied("NVIDIA physical VRAM monitor failed")
        rows=process.stdout.strip().splitlines()
        if len(rows)!=1:
            raise PhysicalGPUBudgetDenied("expected one NVIDIA RTX GPU")
        values=[int(v.strip()) for v in rows[0].split(",")]
        if len(values)!=3:
            raise PhysicalGPUBudgetDenied("incomplete NVIDIA VRAM fields")
    except (OSError,ValueError,subprocess.TimeoutExpired) as exc:
        raise PhysicalGPUBudgetDenied("physical memory reading unavailable") from exc
    return MemoryObservation(mem["MemTotal"],mem["MemAvailable"],*values)


def validate_bounded_model_request(body: bytes) -> str:
    """Reject caller-controlled model memory/context expansion and CPU fallback.

    The physical GPU remains an allowlisted model in an isolated runtime, not a
    request parameter. Reject unsafe overrides before any resource admission.
    """
    if len(body)>262144:
        raise PhysicalGPUBudgetDenied("DEV inference payload exceeds fixed size limit")
    try:
        request=json.loads(body)
    except (ValueError,UnicodeDecodeError) as exc:
        raise PhysicalGPUBudgetDenied("invalid inference JSON") from exc
    if not isinstance(request,dict) or not isinstance(request.get("model"),str):
        raise PhysicalGPUBudgetDenied("exact model required")
    options=request.get("options",{})
    if not isinstance(options,dict):
        raise PhysicalGPUBudgetDenied("invalid model options")
    safe_options={"num_ctx","num_predict","temperature","top_p","top_k",
                  "min_p","seed","repeat_penalty","repeat_last_n","stop"}
    if set(options) - safe_options:
        raise PhysicalGPUBudgetDenied("unapproved llama runtime memory/performance option")
    for key in ("num_gpu","main_gpu","numa","low_vram","tensor_split",
                "num_batch","context_length","n_gpu_layers"):
        if key in options or key in request:
            raise PhysicalGPUBudgetDenied("caller cannot override physical GPU placement")
    for key,maximum in (("num_ctx",4096),("num_predict",2048),
                        ("max_tokens",2048),("max_completion_tokens",2048)):
        for item in (options,request):
            if key in item:
                n=item[key]
                if type(n) is not int or not 0 < n <= maximum:
                    raise PhysicalGPUBudgetDenied("bounded context/output limit exceeded")
    keep=request.get("keep_alive",0)
    if type(keep) is int:
        allowed=(0<=keep<=300)
    elif isinstance(keep,str):
        if keep.isdigit():
            allowed=int(keep)<=300
        elif keep.endswith("s") and keep[:-1].isdigit():
            allowed=int(keep[:-1])<=300
        elif keep.endswith("m") and keep[:-1].isdigit():
            allowed=int(keep[:-1])<=5
        else:
            allowed=False
    else:
        allowed=False
    if not allowed:
        raise PhysicalGPUBudgetDenied("unbounded Ollama memory residency")
    return request["model"]
