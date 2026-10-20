#!/usr/bin/env python3
"""DEV-only one-shot hardware acceptance of Gateway's cooperative adapters.

Does not alter systemd, current release, permissions or GPU driver.
Requires both production engines idle and records a separate DEV marker.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / ("candidate/src" if os.environ.get("RM_TEST_CANDIDATE") == "1" else "src")))
from ai_bridge.gateway.app import create_gateway_app
from ai_bridge.settings import Settings

OLD = Path("/opt/ai-platform/releases/stage-o-28e3ea214660")
CHECKS = ("ollama", "ai-gateway", "ai-bridge", "comfyui")
DEV_MARKER = ROOT / ".rm-hardware-acceptance-gpu.dirty"
REPORT = ROOT / "RM_ENGINE_HARDWARE_ACCEPTANCE_RESULT.json"


def must(condition, message):
    if not condition:
        raise RuntimeError(message)


async def get(client, url):
    response = await client.get(url, timeout=5)
    response.raise_for_status()
    return response.json()


async def production_preflight(host):
    current = Path("/opt/ai-platform/current").resolve()
    must(current == OLD, "production release changed")
    must(not DEV_MARKER.exists(), "DEV dirty marker exists")
    must(not Path("/var/lib/ai-platform-gpu/residency.blocked").exists(),
         "production GPU dirty marker exists")
    must(not Path("/var/lib/ai-platform-gpu/managed-worker.dirty").exists(),
         "managed worker dirty marker exists")
    must(not Path("/home/harrypotter/.local/state/ai-platform/gpu-residency.blocked").exists(),
         "user GPU dirty marker exists")
    for unit in CHECKS:
        proc = await asyncio.create_subprocess_exec("systemctl", "is-active",
                                                    unit + ".service",
                                                    stdout=asyncio.subprocess.PIPE)
        out, _ = await proc.communicate()
        must(proc.returncode == 0 and out.strip() == b"active",
             "service not active: " + unit)
    status = await get(host, "http://127.0.0.1:11435/status")
    must(status.get("active_count") == 0 and status.get("queued_count") == 0
         and status.get("admission_blocked") is False
         and status.get("resource_leases", {}).get("lease_count") == 0
         and status.get("gpu_residency", {}).get("state") == "llm"
         and status["gpu_residency"]["recovery_required"] is False,
         "production RM is busy/dirty")
    models = await get(host, "http://127.0.0.1:11434/api/ps")
    must(models.get("models") == [], "Ollama already has resident models")
    comfy = await get(host, "http://127.0.0.1:8188/ai-platform/residency")
    must(comfy.get("schema_version") == 1
         and all(comfy.get(k) == 0 for k in ("queue_running", "queue_pending", "loaded_models"))
         and comfy.get("cleanup_pending") is False,
         "ComfyUI not idle")
    return status, comfy


async def run():
    info = {"schema": 1,
            "time": datetime.now(timezone.utc).isoformat(),
            "outcome": "BLOCKED",
            "dev_ref": "0016bbe",
            "production_release": str(OLD),
            "real_ollama_gpu_embedding": "NOT_TESTED",
            "real_comfyui_media_transition": "NOT_TESTED",
            "automatic_n1_grant": "NOT_ADMITTED",
            "gpu_reuse_safe": "NOT_VERIFIED"}
    REPORT.write_text(json.dumps(info, indent=2) + "\n")
    async with httpx.AsyncClient(trust_env=False) as host:
        try:
            await production_preflight(host)
            info["production_preflight"] = "PASS"
            settings = Settings(
                _env_file=None,
                ollama_url="http://127.0.0.1:11434",
                gateway_comfy_url="http://127.0.0.1:8188",
                gateway_gpu_marker=DEV_MARKER,
                gateway_gpu_transition_timeout=45.0,
                gateway_comfy_idle_reserve_bytes=67108864,
                gateway_max_concurrency=1,
                gateway_admission_strategy="legacy",
                platform_api_token=None,
            )
            app = create_gateway_app(settings)
            async with app.router.lifespan_context(app):
                async with httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=app),
                    base_url="http://dev-accept.invalid",
                    trust_env=False, timeout=90,
                ) as client:
                    initial = (await client.get("/status")).json()
                    must(initial["resource_manager"]["state"] == "IDLE",
                         "DEV resource state is not IDLE")
                    must(len(initial["resource_manager"]["engines"]) == 3,
                         "missing registered engines")
                    must(next(e for e in initial["resource_manager"]["engines"]
                              if e["id"] == "vision")["execution_available"] is False,
                         "Vision unexpectedly executable")
                    # Real Ollama embedding -> ROCm/Vulkan model execution.
                    response = await client.post("/api/embed", json={
                        "model": "bge-m3:latest",
                        "input": "RM acceptance: 2026-10-20",
                        "keep_alive": 0,
                    }, timeout=90)
                    must(response.status_code == 200,
                         "real Ollama embedding rejected: " + str(response.status_code))
                    vecs = response.json().get("embeddings")
                    must(isinstance(vecs, list) and len(vecs) == 1
                         and len(vecs[0]) == 1024, "invalid embedding output")
                    info["real_ollama_gpu_embedding"] = "PASS_1024"
                    await production_preflight(host)
                    lease = await client.post("/resource/leases", json={
                        "workload": "media-image", "priority": 50, "source": "rm-hardware-accept"})
                    must(lease.status_code == 201, "DEV lease rejected")
                    lease_id = lease.json()["lease_id"]
                    use_id = None
                    try:
                        started = await client.post(
                            f"/resource/leases/{lease_id}/uses",
                            json={"provider": "comfyui-local", "capability": "image-generation"},
                            timeout=75)
                        must(started.status_code == 201, "ComfyUI media phase failed: " +
                             str(started.status_code))
                        use_id = started.json()["use_id"]
                        status = (await client.get("/status")).json()
                        info["media_observation"] = {
                            "view": status["resource_manager"]["state"],
                            "active_engine": status["resource_manager"]["active_engine"],
                            "reason": status["resource_manager"]["reason"],
                            "legacy_state": status["gpu_residency"]["state"],
                            "active_count": status["active_count"],
                            "lease_count": status["resource_leases"]["lease_count"],
                            "job_state": (status["active"][0]["job"].get("state")
                                          if status["active"] else None),
                            "workload_providers": sorted({
                                x["provider"] for a in status["active"]
                                for x in a["job"].get("workload", [])}),
                        }
                        must(status["resource_manager"]["state"] == "RUNNING"
                             and status["resource_manager"]["active_engine"] == "comfyui"
                             and status["gpu_residency"]["state"] == "media"
                             and status["resource_leases"]["lease_count"] == 1,
                             "ComfyUI admission/owner mismatch")
                        verify = await client.get(f"/resource/leases/{lease_id}/uses/{use_id}")
                        must(verify.status_code == 200, "ComfyUI verification failed")
                        info["real_comfyui_media_transition"] = "ENTER_PASS"
                    finally:
                        if use_id:
                            ended = await client.delete(f"/resource/leases/{lease_id}/uses/{use_id}",
                                                        timeout=75)
                            must(ended.status_code == 200 and ended.json().get("released") is True,
                                 "ComfyUI release failed")
                        released = await client.delete(f"/resource/leases/{lease_id}")
                        must(released.status_code == 200, "lease release failed")
                    final = (await client.get("/status")).json()
                    must(final["resource_manager"]["state"] == "IDLE"
                         and final["gpu_residency"]["state"] == "llm"
                         and final["active_count"] == 0
                         and final["resource_leases"]["lease_count"] == 0
                         and not DEV_MARKER.exists(), "DEV final cleanup incomplete")
                    info["real_comfyui_media_transition"] = "ENTER_RELEASE_PASS"
                    info["dev_final"] = "IDLE_AND_CLEAN"
            prod, comfy = await production_preflight(host)
            info["production_postflight"] = "PASS"
            info["outcome"] = "REAL_HARDWARE_ACCEPT_PASS"
        except BaseException as exc:
            info["error_type"] = type(exc).__name__
            info["error"] = str(exc)[:300]
            info["outcome"] = "BLOCKED"
        finally:
            REPORT.write_text(json.dumps(info, indent=2, sort_keys=True) + "\n")
            print(json.dumps(info, indent=2, sort_keys=True), flush=True)
    return 0 if info["outcome"] == "REAL_HARDWARE_ACCEPT_PASS" else 2


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run()))
