#!/usr/bin/env python3
"""One-shot, isolated Ollama Qwen3 0.6B inference on RTX 5060 Ti.
No systemd modifications, no production model store, no retries, fail closed.
"""
import datetime as dt
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import urllib.request
import urllib.error

ROOT = Path("/srv/ai-data/staging/egpu-ollama-ai-smoke-20261023")
BOOT = "d05627f7-8703-40d8-bc36-971578675050"
BDF_GPU = "0000:03:00.0"
BDF_BRIDGE = "0000:02:00.0"
MODEL = "qwen3:0.6b"
URL = "http://127.0.0.1:11931"
PORT = 11931
GPU_UUID = "aa94ace8-21b8-783b-a496-72167511f295"


def read(p):
    return Path(p).read_text().strip()


def ensure(x, msg):
    if not x:
        raise RuntimeError(msg)


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


class Log:
    def __init__(self):
        self.fd = os.open(ROOT / "attempt.jsonl",
                          os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        directory = os.open(ROOT, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(self.fd)
            os.fsync(directory)
        finally:
            os.close(directory)

    def event(self, name, **fields):
        raw = (json.dumps(dict(utc=now(), event=name,
                               boot_id=read("/proc/sys/kernel/random/boot_id"),
                               **fields), sort_keys=True) + "\n").encode()
        while raw:
            count = os.write(self.fd, raw)
            ensure(count > 0, "journal write failed")
            raw = raw[count:]
        os.fsync(self.fd)

    def close(self):
        os.close(self.fd)


def preflight():
    ensure(read("/proc/sys/kernel/random/boot_id") == BOOT, "boot ID changed")
    gpu = Path("/sys/bus/pci/devices") / BDF_GPU
    bridge = Path("/sys/bus/pci/devices") / BDF_BRIDGE
    ensure(gpu.is_dir() and bridge.is_dir(), "PCIe GPU or bridge missing")
    ensure(read(gpu / "vendor") == "0x10de" and
           read(gpu / "device") == "0x2d04", "wrong GPU")
    ensure(read(bridge / "vendor") == "0x8086" and
           read(bridge / "device") == "0x5786", "wrong bridge")
    ensure(gpu.resolve().parent == bridge.resolve(), "PCIe topology mismatch")
    ensure((gpu / "driver").is_symlink() and
           (gpu / "driver").resolve().name == "nvidia", "NVIDIA not bound")
    router = Path("/sys/bus/thunderbolt/devices/0-2")
    ensure(router.is_dir() and read(router / "device_name") == "TBGAA" and
           read(router / "authorized") == "1", "wrong USB4 adapter")
    for p in (gpu, bridge):
        ensure(read(p / "current_link_speed") == "8.0 GT/s PCIe" and
               read(p / "current_link_width") == "4", "PCIe lost Gen3 x4")
        for file in ("aer_dev_correctable", "aer_dev_nonfatal", "aer_dev_fatal"):
            vals = [int(l.split()[-1]) for l in read(p / file).splitlines()
                    if l.startswith("TOTAL_")]
            ensure(vals and all(v == 0 for v in vals),
                   "PCIe AER nonzero on " + p.name)
    for service in ("ollama", "comfyui", "ai-gateway", "ai-platform-radio",
                    "nvidia-persistenced"):
        p = subprocess.run(["systemctl", "is-active", service],
                           capture_output=True, text=True, timeout=3)
        ensure(p.stdout.strip() == "inactive", "GPU service active: " + service)
    p = subprocess.run(["journalctl", "-k", "-b", "0", "--no-pager"],
                       capture_output=True, text=True, timeout=5)
    ensure(p.returncode == 0 and "NVRM: Xid" not in p.stdout and
           "GPU has fallen off the bus" not in p.stdout,
           "kernel NVIDIA failure")
    ensure(read("/proc/driver/nvidia/gpus/" + BDF_GPU + "/information").find(
        GPU_UUID) >= 0, "GPU UUID mismatch")


def api(path, payload=None, timeout=15):
    data = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(URL + path, data=data)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def main():
    ensure(sys.argv[1:] == ["--allow-disruptive"], "missing explicit approval")
    ensure(ROOT.is_dir(), "missing NVMe staging")
    preflight()
    log = Log()
    process = None
    log_file = None
    pull_file = None
    outcome = "STOP"
    result = {}
    env = os.environ.copy()
    env.update({
        "OLLAMA_HOST": "127.0.0.1:11931",
        "OLLAMA_MODELS": str(ROOT / "models"),
        "OLLAMA_KEEP_ALIVE": "30s",
        "OLLAMA_NUM_PARALLEL": "1",
        "OLLAMA_MAX_LOADED_MODELS": "1",
        "OLLAMA_MAX_QUEUE": "1",
        "OLLAMA_CONTEXT_LENGTH": "1024",
        "OLLAMA_NOPRUNE": "true",
        "OLLAMA_IGPU_ENABLE": "false",
        "CUDA_VISIBLE_DEVICES": "0",
        "HIP_VISIBLE_DEVICES": "-1",
        "ROCR_VISIBLE_DEVICES": "-1",
        "OLLAMA_DEBUG": "1",
        "LC_ALL": "C",
    })
    ensure((ROOT / "models").is_dir(), "private model dir missing")
    try:
        log.event("PREFLIGHT_PASS", model=MODEL, isolated_port=PORT,
                  model_dir=env["OLLAMA_MODELS"])
        log_file = (ROOT / "server.log").open("x")
        log.event("SERVER_LAUNCH")
        process = subprocess.Popen(["/usr/local/bin/ollama", "serve"],
                                   env=env, cwd=ROOT, stdout=log_file,
                                   stderr=subprocess.STDOUT, start_new_session=True)
        started = time.monotonic()
        while time.monotonic() - started < 25:
            ensure(process.poll() is None, "Ollama isolated server exited")
            try:
                version = api("/api/version", timeout=2)
                log.event("SERVER_READY", version=version)
                break
            except (OSError, urllib.error.URLError):
                time.sleep(0.5)
        else:
            raise RuntimeError("Isolated Ollama server not ready")
        preflight()
        log.event("MODEL_PULL_BEGIN", model=MODEL)
        pull_file = (ROOT / "pull.log").open("x")
        pull = subprocess.run(["/usr/local/bin/ollama", "pull", MODEL],
                              env=env, cwd=ROOT, stdout=pull_file,
                              stderr=subprocess.STDOUT, timeout=180)
        pull_file.close()
        pull_file = None
        ensure(pull.returncode == 0, "model pull failed")
        log.event("MODEL_PULL_PASS", model=MODEL)
        preflight()
        prompt = "Ile wynosi 17 + 25? Odpowiedz tylko liczbą."
        log.event("INFERENCE_BEGIN", prompt=prompt)
        response = api("/api/generate",
                       {"model": MODEL, "prompt": prompt, "stream": False,
                        "think": False, "keep_alive": "30s",
                        "options": {"num_ctx": 1024, "num_predict": 48,
                                    "temperature": 0}}, timeout=120)
        (ROOT / "response.json").write_text(
            json.dumps(response, ensure_ascii=False, indent=2) + "\n")
        log.event("INFERENCE_RETURN",
                  response=response.get("response"),
                  done=response.get("done"), eval_count=response.get("eval_count"),
                  prompt_eval_count=response.get("prompt_eval_count"),
                  eval_duration=response.get("eval_duration"))
        ensure(response.get("done") is True and
               bool(str(response.get("response", "")).strip()), "no model output")
        loaded = api("/api/ps", timeout=5)
        (ROOT / "loaded_models.json").write_text(
            json.dumps(loaded, ensure_ascii=False, indent=2) + "\n")
        models = [x for x in loaded.get("models", [])
                  if x.get("name", "").startswith("qwen3:0.6b")]
        ensure(len(models) == 1, "expected model missing in isolated runner")
        gpu_bytes = int(models[0].get("size_vram", 0))
        total_bytes = int(models[0].get("size", 0))
        ensure(gpu_bytes > 0, "CPU-only inference; no GPU offload")
        preflight()
        log.event("GPU_OFFLOAD_PASS", size_vram=gpu_bytes, size_total=total_bytes)
        ensure("42" in str(response["response"]),
               "model answer failed simple sanity check")
        outcome = "PASS"
        result = {"status": outcome, "model": MODEL,
                  "answer": response["response"].strip(),
                  "vram_bytes": gpu_bytes, "model_size_bytes": total_bytes,
                  "eval_tokens": response.get("eval_count"),
                  "journal": str(ROOT / "attempt.jsonl")}
        log.event("MODEL_INFERENCE_PASS", **result)
        print(json.dumps(result, ensure_ascii=False), flush=True)
    except Exception as err:
        result = {"status": "STOP", "reason": str(err),
                  "journal": str(ROOT / "attempt.jsonl")}
        try:
            log.event("STOP", reason=str(err))
        except Exception:
            pass
        print(json.dumps(result, ensure_ascii=False), flush=True)
    finally:
        if process is not None and process.poll() is None:
            try:
                if outcome == "PASS":
                    log.event("UNLOAD_BEGIN")
                    api("/api/generate", {"model": MODEL,
                                          "keep_alive": 0}, timeout=15)
                    log.event("UNLOAD_REQUESTED")
            except Exception as err:
                log.event("UNLOAD_ERROR", reason=str(err))
                outcome = "STOP"
            try:
                log.event("SERVER_STOP_BEGIN", pid=process.pid)
                os.killpg(process.pid, signal.SIGTERM)
                process.wait(timeout=8)
                log.event("SERVER_STOPPED", returncode=process.returncode)
            except Exception as err:
                log.event("SERVER_STOP_ERROR", reason=str(err))
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=3)
                except Exception:
                    pass
        if pull_file is not None:
            pull_file.close()
        if log_file is not None:
            log_file.close()
        log.event("END", outcome=outcome)
        log.close()
    if outcome != "PASS":
        raise SystemExit(2)


if __name__ == "__main__":
    try:
        main()
    except Exception as ex:
        print(json.dumps({"status": "STOP", "reason": str(ex)}), flush=True)
        raise SystemExit(2)
