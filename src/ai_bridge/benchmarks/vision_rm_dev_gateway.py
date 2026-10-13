#!/usr/bin/env python3
"""Isolated DEV Gateway: real RM + PID/cgroup/DRM observer, MOCK providers.

No real Ollama/ComfyUI I/O. Only CPU dummy Vision worker is supported, never a
GPU model. Runs under ai-gateway-rm on 127.0.0.1:11575, never production port.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path

import httpx
import uvicorn

from ai_bridge.gateway.app import create_gateway_app
from ai_bridge.settings import Settings


def mock_upstream(request: httpx.Request) -> httpx.Response:
    path=request.url.path
    if path=="/api/ps":
        return httpx.Response(200,json={"models":[]})
    if path=="/api/tags":
        return httpx.Response(200,json={"models":[]})
    if path=="/queue":
        return httpx.Response(200,json={"queue_running":[],"queue_pending":[]})
    if path=="/ai-platform/residency":
        return httpx.Response(200,json={
            "schema_version":1,"queue_running":0,"queue_pending":0,
            "loaded_models":0,"cleanup_pending":False})
    if path=="/system_stats":
        return httpx.Response(200,json={"devices":[{"torch_vram_total":0}]})
    return httpx.Response(503,json={"error":"dev_fake_provider_not_supported"})


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def make_app():
    gate=Path("/usr/local/libexec/ai-platform/vision-worker-gate.py")
    worker=Path("/usr/local/libexec/ai-platform/vision-rm-dev-cpu-worker.py")
    token=Path("/etc/ai-platform/vision-rm/executor.token")
    observer=Path("/run/ai-vision-gpu-observer/observer.sock")
    marker=Path("/var/lib/ai-gateway-rm/dev-gpu-test.blocked")
    if (marker.exists() or not observer.is_socket() or
        not gate.is_file() or not worker.is_file() or os.geteuid()!=993):
        raise RuntimeError("DEV Gateway preflight unavailable")
    settings=Settings(
        _env_file=None,
        gateway_vision_external_enabled=True,
        gateway_vision_executor_token_file=token,
        gateway_vision_gpu_marker=marker,
        gateway_vision_worker_uid=994,
        gateway_vision_gpu_observer_socket=observer,
        gateway_vision_strict_gpu_clients=True,
        gateway_vision_worker_gate_path=gate,
        gateway_vision_worker_gate_sha256=digest(gate),
        gateway_vision_allowed_scripts={str(worker):digest(worker)},
        gateway_vision_allowed_checkpoints={},
        gateway_max_concurrency=4,
        gateway_gpu_transition_timeout=20,
        gateway_host="127.0.0.1",
        gateway_port=11575,
        gateway_comfy_url="http://127.0.0.1:8188",
        ollama_url="http://127.0.0.1:11434",
    )
    backend=httpx.MockTransport(mock_upstream)
    return create_gateway_app(settings,upstream_transport=backend,
                              residency_transport=backend)


if __name__=="__main__":
    uvicorn.run(make_app(),host="127.0.0.1",port=11575,
                log_level="warning",access_log=False)
