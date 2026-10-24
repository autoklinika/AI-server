"""CPU-only full /foto wiring: actual subprocesses and HTTP, synthetic model replies.

A fake Ollama response and a fake ComfyUI HTTP server are deliberately used.
No physical GPU, model inference, live Telegram CLI, or production port touched.
"""
from __future__ import annotations

from contextlib import contextmanager
import importlib.util
import json
import os
from pathlib import Path
import shutil
import socket
import struct
import subprocess
import sys
import threading
import time
import uuid
import zlib

from fastapi import FastAPI, Request
import httpx
import pytest
import uvicorn

from ai_bridge.gateway.app import create_gateway_app
from ai_bridge.settings import Settings
from test_rm_comfy_ondemand_dev import Controller, MockServices

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT_SCRIPT = ROOT / "tools/local_image/prepare_comfy_fullchain_isolated_dev.py"
PORT_GATEWAY, PORT_COMFY = 11656, 11657
MODEL = "qwen3.6:35b-hermes64k"
TARGET = "telegram:DEV_UNROUTABLE_NO_SEND"

spec = importlib.util.spec_from_file_location("snapshot_comfy_http_e2e", SNAPSHOT_SCRIPT)
assert spec and spec.loader
snapshot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(snapshot)


def _free_port(port: int) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(.4)
        assert sock.connect_ex(("127.0.0.1", port)) != 0, (
            f"DEV test refuses occupied port {port}"
        )


def _start_http(app: FastAPI, port: int) -> tuple[uvicorn.Server, threading.Thread]:
    _free_port(port)
    server = uvicorn.Server(uvicorn.Config(
        app, host="127.0.0.1", port=port, log_level="error",
        access_log=False, lifespan="on", loop="asyncio"))
    thread = threading.Thread(target=server.run, daemon=True,
                              name=f"rm-dev-foto-{port}")
    thread.start()
    started = time.monotonic()
    while not server.started:
        assert thread.is_alive(), f"DEV service {port} failed"
        assert time.monotonic() - started < 8, f"DEV service {port} timeout"
        time.sleep(.04)
    return server, thread


def _png(width=256, height=256) -> bytes:
    """Valid tiny synthetic PNG for transport only, NEVER GPU evidence."""
    def chunk(kind, data):
        return (struct.pack(">I", len(data)) + kind + data
                + struct.pack(">I", zlib.crc32(kind + data) & 0xffffffff))
    pixels = (b"\x00" + b"\x00\x00\x00" * width) * height
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height,
                                          8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(pixels))
            + chunk(b"IEND", b""))


def _build_snapshot(path: Path, monkeypatch) -> None:
    monkeypatch.setattr(snapshot, "TARGET", path)
    path.mkdir(mode=0o700)
    for name in ("tools", "src", "input", "output", "temp", "user"):
        (path / name).mkdir(mode=0o700)
    shutil.copytree(ROOT / "src/ai_bridge", path / "src/ai_bridge",
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    for rel in snapshot.SOURCE_FILES:
        target = path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(snapshot.transform(rel, (ROOT / rel).read_text()))
        target.chmod(0o700 if rel in snapshot.GENERATORS else 0o600)
    # Strictly verify there is no copy of original production ports in
    # any of the execution entrypoints.
    for rel in snapshot.PORT_GATEWAY_FILES + snapshot.GENERATORS:
        text = (path / rel).read_text()
        assert "127.0.0.1:11435" not in text
        assert "127.0.0.1:8188" not in text


@contextmanager
def _servers(snapshot_path, *, malformed=False):
    controller = Controller()
    mock = MockServices(controller)
    observed = {"qwen_calls": [], "flux_workflows": [], "history_calls": []}

    def upstream(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/chat/completions":
            payload = json.loads(request.content)
            observed["qwen_calls"].append({
                "model": payload["model"],
                "lease_held_by_gateway": (
                    len(gateway.state.resource_leases._leases) == 1
                    and any(item.in_use for item in
                            gateway.state.resource_leases._leases.values())
                ),
                "control_header_stripped_upstream":
                    "x-ai-resource-lease" not in request.headers,
                "messages": len(payload["messages"]),
            })
            assert payload["model"] == MODEL
            # Control headers are consumed by RM and intentionally NOT
            # forwarded to Ollama (least-privilege upstream contract).
            assert "x-ai-resource-lease" not in request.headers
            content = (
                "not valid JSON"
                if malformed else
                json.dumps({"intent": "generate", "prompt":
                            "A blue digital oscilloscope on a clean workbench."})
            )
            return httpx.Response(200, json={"choices": [
                {"message": {"content": content}}
            ]})
        return mock.ollama(request)

    gateway = create_gateway_app(Settings(
        _env_file=None,
        gateway_host="127.0.0.1",
        gateway_port=PORT_GATEWAY,
        gateway_comfy_url=f"http://127.0.0.1:{PORT_COMFY}",
        ollama_url="http://mocked-ollama.dev.invalid",
        gateway_gpu_marker=snapshot_path / "dev-residency.blocked",
        gateway_gpu_transition_timeout=2,
        gateway_max_concurrency=1,
        gateway_comfy_ondemand_dev_mode=True,
        gateway_vision_radio_enabled=False,
    ), upstream_transport=httpx.MockTransport(upstream),
        residency_transport=httpx.MockTransport(mock.comfy),
        comfy_process_controller=controller)
    # Build a real loopback HTTP renderer stub, not a real GPU task.
    image_name = "SYNTHETIC_CPU_TEST_00001_.png"
    image_path = snapshot_path / "output" / image_name
    fake_comfy = FastAPI()

    @fake_comfy.get("/system_stats")
    async def stats():
        return {"devices": [{"torch_vram_total": 0}]}

    @fake_comfy.post("/prompt")
    async def prompt(request: Request):
        assert controller.active, "GPU emulator not granted by RM"
        received = await request.json()
        workflow = received["prompt"]
        observed["flux_workflows"].append(workflow)
        assert any(node["class_type"] == "UNETLoader"
                   and node["inputs"]["unet_name"] == "flux-2-klein-4b-fp8.safetensors"
                   for node in workflow.values())
        assert any(node["class_type"] == "CLIPLoader"
                   and node["inputs"]["clip_name"] == "qwen_3_4b.safetensors"
                   for node in workflow.values())
        assert any(node["class_type"] == "VAELoader"
                   and node["inputs"]["vae_name"] == "flux2-vae.safetensors"
                   for node in workflow.values())
        assert any(node["class_type"] == "EmptyFlux2LatentImage"
                   and node["inputs"]["width"] == node["inputs"]["height"] == 256
                   for node in workflow.values())
        image_path.write_bytes(_png())
        return {"prompt_id": "cpu-synthetic-dev-workflow", "node_errors": {}}

    @fake_comfy.get("/history/{prompt_id}")
    async def history(prompt_id: str):
        observed["history_calls"].append(prompt_id)
        assert prompt_id == "cpu-synthetic-dev-workflow"
        return {prompt_id: {
            "status": {"status_str": "success"},
            "outputs": {"13": {"images": [{
                "filename": image_name, "subfolder": "", "type": "output"}]}}
        }}

    s_comfy, t_comfy = _start_http(fake_comfy, PORT_COMFY)
    try:
        s_gateway, t_gateway = _start_http(gateway, PORT_GATEWAY)
        controller.residency = gateway.state.resource_leases.residency
        try:
            yield controller, mock, observed, gateway, image_path
        finally:
            s_gateway.should_exit = True
            t_gateway.join(timeout=8)
            assert not t_gateway.is_alive()
    finally:
        s_comfy.should_exit = True
        t_comfy.join(timeout=8)
        assert not t_comfy.is_alive()


def _run_worker(snapshot_path: Path, *, prompt: str) -> tuple[subprocess.CompletedProcess, dict]:
    job = snapshot_path / "test-job"
    job.mkdir(mode=0o700)
    (job / "request.json").write_text(json.dumps({
        "job_id": "ISOLATED_CPU_NO_GPU",
        "prompt": prompt,
        "target": TARGET,
        "input_image": None,
        "mode": "generate",
    }))
    py = Path("/home/harrypotter/AI-server/.venv/bin/python")
    assert py.is_file()
    env = {
        **os.environ,
        "PYTHONPATH": str(snapshot_path / "src"),
        "PATH": f"{py.parent}:{os.environ.get('PATH', '')}",
        "HERMES_RESOURCE_GATEWAY_URL": f"http://127.0.0.1:{PORT_GATEWAY}",
        "HERMES_FOTO_QWEN_URL": (
            f"http://127.0.0.1:{PORT_GATEWAY}/clients/hermes/v1/chat/completions"),
        "HERMES_FOTO_QWEN_MODEL": MODEL,
        "HERMES_FOTO_TEXT_GENERATOR":
            str(snapshot_path / "tools/local_image/generate_image.py"),
        "HERMES_FOTO_EDIT_GENERATOR":
            str(snapshot_path / "tools/local_image/generate_image_edit.py"),
        "HERMES_RESOURCE_QUEUE_NOTICE_AFTER": "3",
        "HERMES_FOTO_QWEN_TIMEOUT": "12",
    }
    proc = subprocess.run(
        [str(py), str(snapshot_path / "tools/local_image/hermes_foto_dispatch_global.py"),
         "--worker", str(job)],
        cwd=str(snapshot_path),
        env=env, capture_output=True, text=True, timeout=36, check=False,
    )
    return proc, json.loads((job / "result.json").read_text())


@pytest.mark.parametrize("malformed", [False, True])
def test_actual_hermes_compiler_and_generator_subprocess_endpoints(
    tmp_path, monkeypatch, malformed
):
    """Mock responses only; worker/compiler/generator/token guard are real code."""
    snapshot_path = tmp_path / "isolated"
    _build_snapshot(snapshot_path, monkeypatch)
    assert not (snapshot_path / "captured-deliveries.jsonl").exists()
    with _servers(snapshot_path, malformed=malformed) as (
        controller, mock, observed, gateway, png
    ):
        proc, result = _run_worker(
            snapshot_path, prompt="Niebieski oscyloskop na stole warsztatowym.")
        if malformed:
            assert proc.returncode == 1, (proc.stderr, result)
            assert result["ok"] is False
            assert result["qwen_used"] is False
            assert controller.events == []
            assert observed["flux_workflows"] == []
            assert not png.exists()
        else:
            assert proc.returncode == 0, (proc.stdout, proc.stderr, result)
            assert result["ok"] is True
            assert result["qwen_used"] is True
            assert result["qwen_intent"] == "generate"
            assert result["path"] == str(png)
            assert png.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
            assert controller.events == ["start", "stop"]
            assert len(observed["flux_workflows"]) == 1
            assert observed["history_calls"]
        assert len(observed["qwen_calls"]) == 1
        assert observed["qwen_calls"][0]["lease_held_by_gateway"] is True
        assert observed["qwen_calls"][0]["control_header_stripped_upstream"] is True
        capture = snapshot_path / "captured-deliveries.jsonl"
        messages = [json.loads(line) for line in capture.read_text().splitlines()]
        assert len(messages) == 1
        assert messages[0]["target"] == "DEV_CAPTURE_ONLY"
        assert messages[0]["message"].startswith("MEDIA:" if not malformed else "❌")
        # End-to-end acknowledgment is not enough: verify the actual
        # scheduler has returned to IDLE before the next lease is admitted.
        with httpx.Client(base_url=f"http://127.0.0.1:{PORT_GATEWAY}",
                          timeout=3, trust_env=False) as client:
            health = client.get("/health").json()
        assert health["status"] == "ok"
        assert health["resource_manager"]["state"] == "IDLE"
        assert health["scheduler"]["active_count"] == 0
        assert health["scheduler"]["queued_count"] == 0
        assert health["gpu_residency"]["recovery_required"] is False
        assert gateway.state.scheduler.admission_blocked is False
        assert not mock.ollama_resident
        assert controller.residency.state == "llm"
        assert not controller.residency.marker.exists()
