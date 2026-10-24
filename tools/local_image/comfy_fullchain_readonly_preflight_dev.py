#!/usr/bin/env python3
"""Read-only DEV preflight. No inference, GPU grant, unit changes, or Telegram."""
from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import subprocess
import sys
from urllib.request import urlopen

GATEWAY = "http://127.0.0.1:11435/health"
OLLAMA_TAGS = "http://127.0.0.1:11434/api/tags"
OLLAMA_PS = "http://127.0.0.1:11434/api/ps"
COMFY_STATE = "http://127.0.0.1:8188/ai-platform/residency"
COMFY_QUEUE = "http://127.0.0.1:8188/queue"
MODEL = "qwen3.6:35b-hermes64k"
ROOT = Path(__file__).resolve().parents[2]
ASSETS = {
    "flux2_klein_fp8": Path("/opt/comfyui/data/models/diffusion_models/flux-2-klein-4b-fp8.safetensors"),
    "flux2_text_encoder": Path("/opt/comfyui/data/models/text_encoders/qwen_3_4b.safetensors"),
    "flux2_vae": Path("/opt/comfyui/data/models/vae/flux2-vae.safetensors"),
}
GPU_NODES = ["/dev/kfd", "/dev/dri/renderD128",
             "/dev/nvidia0", "/dev/nvidiactl", "/dev/nvidia-uvm"]
MARKERS = [
    "/srv/ai-data/staging/comfy-ondemand-maintenance-dev-20261023/dev-residency.blocked",
    "/srv/ai-data/staging/comfy-ondemand-faults-dev-20261024/dev-residency.blocked",
]
UNITS = ["ai-gateway.service", "comfyui.service", "ollama.service",
         "ai-rm-comfy-ondemand-dev.service"]


def read_json(url: str) -> dict:
    # Every network operation is GET; no prompt submission is possible.
    with urlopen(url, timeout=4) as r:
        value = json.load(r)
    if not isinstance(value, dict):
        raise ValueError("unexpected response type")
    return value


def command(*args: str) -> str:
    result = subprocess.run(args, capture_output=True, text=True, timeout=5,
                            check=False)
    if result.returncode:
        raise RuntimeError(f"{args[0]} failed ({result.returncode})")
    return result.stdout.strip()


def main() -> int:
    out: dict = {
        "schema_version": 1, "kind": "DEV_READ_ONLY_FULLCHAIN_PREFLIGHT",
        "host": os.uname().nodename,
        "production_modified": False, "gpu_test_executed": False,
        "telegram_sent": False, "gpu_reuse_safe": "NOT_VERIFIED",
        "n1_shared_gpu_grants": "NOT_ADMITTED", "errors": [],
    }

    try:
        values = {}
        for line in Path("/proc/meminfo").read_text().splitlines():
            name, _, value = line.partition(":")
            if name in {"MemTotal", "MemAvailable", "SwapTotal"}:
                values[name] = int(value.strip().split()[0]) * 1024
        out["host_memory_bytes"] = values
    except (OSError, ValueError, IndexError) as exc:
        out["errors"].append(f"meminfo:{type(exc).__name__}")

    try:
        h = read_json(GATEWAY)
        out["gateway"] = {
            "ok": h.get("status") == "ok",
            "rm_state": h.get("resource_manager", {}).get("state"),
            "rm_active_engine": h.get("resource_manager", {}).get("active_engine"),
            "recovery_required": h.get("gpu_residency", {}).get("recovery_required"),
            "scheduler_active_count": h.get("scheduler", {}).get("active_count"),
            "scheduler_queued_count": h.get("scheduler", {}).get("queued_count"),
        }
    except (OSError, ValueError, KeyError, TimeoutError) as exc:
        out["errors"].append(f"gateway:{type(exc).__name__}")

    try:
        tags = read_json(OLLAMA_TAGS)
        models = tags.get("models", [])
        found = next((m for m in models if m.get("name") == MODEL), None)
        out["qwen"] = {"model": MODEL, "present": found is not None,
                       "disk_bytes": found.get("size") if found else None,
                       "inference_run": False, "context_configured": 65536}
        ps = read_json(OLLAMA_PS)
        out["ollama_resident_models"] = [
            m.get("name") for m in ps.get("models", []) if isinstance(m, dict)
        ]
    except (OSError, ValueError, KeyError, TimeoutError) as exc:
        out["errors"].append(f"ollama:{type(exc).__name__}")

    try:
        state = read_json(COMFY_STATE)
        queue = read_json(COMFY_QUEUE)
        out["production_comfy"] = {
            "schema_version": state.get("schema_version"),
            "loaded_models": state.get("loaded_models"),
            "queue_running": state.get("queue_running"),
            "queue_pending": state.get("queue_pending"),
            "cleanup_pending": state.get("cleanup_pending"),
            "http_queue_running": len(queue.get("queue_running", [])),
            "http_queue_pending": len(queue.get("queue_pending", [])),
        }
    except (OSError, ValueError, KeyError, TimeoutError) as exc:
        out["errors"].append(f"comfy:{type(exc).__name__}")

    for name, path in ASSETS.items():
        try:
            s = path.stat()
            if not stat.S_ISREG(s.st_mode):
                raise ValueError("not a regular file")
            out.setdefault("flux2_assets_bytes", {})[name] = s.st_size
        except (OSError, ValueError) as exc:
            out["errors"].append(f"asset:{name}:{type(exc).__name__}")

    for node in GPU_NODES:
        try:
            s = os.stat(node)
            out.setdefault("gpu_node_permissions", {})[node] = oct(stat.S_IMODE(s.st_mode))
        except OSError as exc:
            out["errors"].append(f"gpu_node:{node}:{type(exc).__name__}")

    for unit in UNITS:
        try:
            out.setdefault("systemd", {})[unit] = {
                "active": command("systemctl", "show", "-P", "ActiveState", unit),
                "main_pid": command("systemctl", "show", "-P", "MainPID", unit),
            }
        except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
            out["errors"].append(f"systemd:{unit}:{type(exc).__name__}")

    try:
        out["nvidia"] = command("nvidia-smi",
            "--query-gpu=name,pstate,memory.used,memory.total,temperature.gpu",
            "--format=csv,noheader,nounits")
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
        out["errors"].append(f"nvidia:{type(exc).__name__}")

    out["active_dev_recovery_markers"] = [p for p in MARKERS if Path(p).exists()]
    unit_path = ROOT / "deploy/comfy-ondemand-dev/ai-rm-comfy-ondemand-dev.service"
    try:
        unit_text = unit_path.read_text()
        out["dev_unit_memory_max"] = next(
            (line.removeprefix("MemoryMax=") for line in unit_text.splitlines()
             if line.startswith("MemoryMax=")), None)
    except OSError as exc:
        out["errors"].append(f"dev_unit:{type(exc).__name__}")

    out["fullchain_live_gate"] = "BLOCKED"
    out["fullchain_blockers"] = [
        "Operator-only independent rollback window not yet authorized",
        "Qwen actual inference/RAM/cgroup/GPU residency not measured",
        "Generator and external media guard DEV endpoint isolation not yet accepted",
        "Full FLUX2 Klein memory and AMD driver safe reuse not verified",
        "ComfyUI production holds Radeon file descriptors while RM is IDLE",
        "System-wide GPU bypass prevention not yet accepted",
    ]
    out["preflight"] = "PASS" if not out["errors"] else "INCOMPLETE"
    print(json.dumps(out, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if not out["errors"] else 2


if __name__ == "__main__":
    sys.exit(main())
