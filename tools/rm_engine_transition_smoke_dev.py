"""DEV-only manual service-transition smoke; NOT N1 admission or GPU E_safe.

Run one engine at a time, then inspect the report before choosing the next.
No root privileges, systemd writes, GPU reset, or arbitrary commands.
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import urllib.request

BASE = Path("/srv/ai-data/evaluation/rm-exclusive-handoff-dev-20261019")
LOGROOT = BASE / "hardware-smoke"
SERVICES = ("gdm.service", "ai-gateway.service", "ai-bridge.service",
            "ollama.service", "comfyui.service", "ai-bridge-analysis.timer")
DEV = ("/dev/kfd", "/dev/dri/renderD128")


def verify_offline():
    for service in SERVICES:
        p = subprocess.run(["systemctl", "is-active", service], text=True,
                           capture_output=True, timeout=3)
        if p.stdout.strip() != "inactive":
            raise RuntimeError(f"Service not inactive: {service} = {p.stdout.strip()}")
    return True


def gpu_clients():
    nodes = Path("/sys/class/kfd/kfd/proc")
    kfd = tuple(sorted(x.name for x in nodes.iterdir()))
    p = subprocess.run(["fuser", *DEV], capture_output=True, text=True, timeout=4)
    if p.returncode not in (0, 1):
        raise RuntimeError("GPU FD inventory unavailable")
    owners = tuple(sorted(p.stdout.split()))
    return {"kfd": kfd, "fuser": owners}


def require_idle():
    verify_offline()
    state = gpu_clients()
    if state["kfd"] or state["fuser"]:
        raise RuntimeError(f"GPU has visible owners: {state}")
    return state


def http_json(method: str, url: str, payload=None, *, timeout=3.0):
    data = None if payload is None else json.dumps(payload).encode("utf8")
    headers = {"Content-Type": "application/json"} if data else {}
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(request, timeout=timeout) as resp:
        if resp.status != 200:
            raise RuntimeError(f"HTTP status {resp.status}")
        return json.loads(resp.read(1_000_000))


def await_server(child, url: str, timeout_s: float):
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if child.poll() is not None:
            raise RuntimeError(f"engine exited during startup: {child.returncode}")
        try:
            return http_json("GET", url, timeout=1.3)
        except (OSError, ValueError):
            time.sleep(0.35)
    raise TimeoutError(f"engine startup not ready: {url}")


def stop_owned_group(child):
    if child is None:
        return
    if child.poll() is None:
        os.killpg(child.pid, signal.SIGTERM)
        try:
            child.wait(timeout=18)
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("owned engine did not stop after SIGTERM; no new engine") from exc


def observe_empty_repeated():
    samples = []
    stable = 0
    for _ in range(36):
        state = gpu_clients()
        samples.append(state)
        if not state["kfd"] and not state["fuser"]:
            stable += 1
        else:
            stable = 0
        if stable >= 3:
            return samples
        time.sleep(.25)
    raise RuntimeError(f"GPU remained occupied; last samples: {samples[-5:]}")


def run(stage: str, attempt: str):
    if os.geteuid() == 0:
        raise RuntimeError("do not run as root")
    LOGROOT.mkdir(exist_ok=True)
    folder = LOGROOT / attempt
    if folder.exists():
        raise RuntimeError("attempt path exists: no replay")
    with (LOGROOT / ".single-engine.lock").open("a") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        folder.mkdir(mode=0o700)
        result = {"stage": stage, "attempt": attempt, "start_time": time.time(),
                  "status": "DIRTY", "n1_gpu_grant": "NOT_ADMITTED",
                  "gpu_reuse_safe": "NOT_VERIFIED"}
        child = None
        error = None
        try:
            result["preflight"] = require_idle()
            env = os.environ.copy()
            env["PYTHONDONTWRITEBYTECODE"] = "1"
            if stage == "ollama":
                env.update({"OLLAMA_HOST": "127.0.0.1:11590",
                            "OLLAMA_MODELS": "/usr/share/ollama/.ollama/models",
                            "OLLAMA_KEEP_ALIVE": "0", "OLLAMA_MAX_LOADED_MODELS": "1",
                            "OLLAMA_NUM_PARALLEL": "1",
                            "OLLAMA_VULKAN": "1", "OLLAMA_IGPU_ENABLE": "1",
                            "OLLAMA_NOPRUNE": "true"})
                command = ["/usr/local/bin/ollama", "serve"]
                cwd = str(BASE)
            elif stage == "comfyui":
                command = ["/opt/comfyui/venv/bin/python",
                           "/opt/comfyui/ComfyUI/main.py", "--listen", "127.0.0.1",
                           "--port", "8189", "--disable-auto-launch",
                           "--disable-all-custom-nodes", "--preview-method", "none",
                           "--user-directory", str(folder / "user"),
                           "--input-directory", str(folder / "input"),
                           "--output-directory", str(folder / "output"),
                           "--temp-directory", str(folder / "temp"),
                           "--models-directory", "/opt/comfyui/data/models"]
                for name in ("user", "input", "output", "temp"):
                    (folder / name).mkdir()
                cwd = "/opt/comfyui/ComfyUI"
            else:
                raise ValueError("unsupported stage")
            with (folder / "engine.log").open("xb") as output:
                child = subprocess.Popen(command, cwd=cwd, env=env,
                                         stdout=output, stderr=subprocess.STDOUT,
                                         stdin=subprocess.DEVNULL, close_fds=True,
                                         start_new_session=True)
            result["leader_pid"] = child.pid
            if stage == "ollama":
                result["version"] = await_server(child, "http://127.0.0.1:11590/api/version", 17)
                result["compute"] = http_json("POST", "http://127.0.0.1:11590/api/embed",
                    {"model": "bge-m3", "input": "rm exclusive hardware transition test",
                     "keep_alive": "1m"}, timeout=65)
                embeddings = result["compute"].get("embeddings")
                if not embeddings or not embeddings[0]:
                    raise RuntimeError("Ollama embed did not return vector")
                result["embedding_dimensions"] = len(embeddings[0])
                del result["compute"]
            elif stage == "comfyui":
                stats = await_server(child, "http://127.0.0.1:8189/system_stats", 45)
                result["runtime_device"] = stats.get("devices")
                if not result["runtime_device"]:
                    raise RuntimeError("ComfyUI returned no devices")
                result["workload"] = "ComfyUI ROCm initialization, not diffusion inference"
            result["gpu_owner_while_running"] = gpu_clients()
            if not any(result["gpu_owner_while_running"].values()):
                raise RuntimeError("no visible GPU owner during engine test")
            result["stage_workload"] = "PASS"
        except BaseException as exc:
            error = f"{type(exc).__name__}: {exc}"
        finally:
            try:
                stop_owned_group(child)
                result["engine_stopped"] = child is not None and child.poll() is not None
                result["postflight_samples"] = observe_empty_repeated()
                verify_offline()
                if error is None:
                    result["status"] = "OBSERVED_LOCAL_LIFECYCLE_PASS"
            except BaseException as exc:
                error = (error + "; " if error else "") + f"cleanup {type(exc).__name__}: {exc}"
            result["finish_time"] = time.time()
            if error:
                result["error"] = error
            with (folder / "result.json").open("x") as out:
                json.dump(result, out, indent=2, sort_keys=True)
                out.flush()
                os.fsync(out.fileno())
        return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=("ollama", "comfyui"))
    parser.add_argument("--attempt", required=True)
    args = parser.parse_args()
    import re
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,55}", args.attempt):
        parser.error("bad attempt ID")
    output = run(args.stage, args.attempt)
    print(json.dumps({k: output.get(k) for k in
          ("stage", "attempt", "status", "leader_pid", "embedding_dimensions",
           "runtime_device", "gpu_owner_while_running", "error", "gpu_reuse_safe")},
          sort_keys=True))
    raise SystemExit(0 if output["status"] == "OBSERVED_LOCAL_LIFECYCLE_PASS" else 2)
