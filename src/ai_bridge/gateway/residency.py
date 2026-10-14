"""Verified shared-GPU residency transitions. Queue ownership outlives failures."""
from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path

import httpx
from datetime import datetime, timezone


class ResidencyError(RuntimeError):
    pass


class GPUResidency:
    def __init__(self, ollama: httpx.AsyncClient, comfy: httpx.AsyncClient,
                 marker: Path, *, timeout: float = 90, poll: float = .25, idle_reserve_bytes: int = 0,
                 require_comfy_extension: bool = True, resume_comfy=None):
        self.ollama, self.comfy = ollama, comfy
        self.marker, self.timeout, self.poll = marker, timeout, poll
        self._model_observations = {"ollama": None, "comfyui": None}
        self.idle_reserve_bytes = idle_reserve_bytes
        self.require_comfy_extension = require_comfy_extension
        self.resume_comfy = resume_comfy
        self.state = "blocked" if marker.exists() else "llm"
        self.cleanup_evidence = None

    def snapshot(self):
        return {"state": self.state, "recovery_required": self.state == "blocked",
                "cleanup_evidence": self.cleanup_evidence}

    def evidence_snapshot(self):
        """Diagnostic facts only; never consumed by admission or release.

        Runtime observations describe an earlier response, not current residency
        or a runtime incarnation. No job, device or generation is inferred here.
        """
        return {
            "schema_version": 1,
            "JOB_TERMINAL": {
                "status": "NOT_OBSERVED", "scope": "individual_job",
                "job_id": None, "observed_at": None, "source": None,
                "reason": "global_status_has_no_selected_job",
            },
            "MODEL_UNLOADED": {
                runtime: {
                    "scope": "all_models_reported_by_configured_runtime",
                    "source": source, "runtime_generation": None,
                    "validity": "POINT_IN_TIME_ONLY",
                    **(observation or {
                        "status": "NOT_OBSERVED", "observed_at": None,
                        "models_unloaded": None, "cleanup_pending": None,
                    }),
                }
                for runtime, source in (
                    ("ollama", "ollama:/api/ps"),
                    ("comfyui", "comfyui:/ai-platform/residency"),
                )
                for observation in (self._model_observations[runtime],)
            },
            "GPU_REUSE_SAFE": {
                "status": "NOT_VERIFIED", "scope": "device_and_generation",
                "device_id": None, "generation": None,
                "observed_at": None, "source": None,
                "reason": "complete_trusted_E_safe_not_deployed",
            },
        }

    @staticmethod
    def _observe_models(runtime, payload, observation):
        # Allowlist scalar facts only: no names, URLs, tokens or raw payloads.
        observation["observed_at"] = datetime.now(timezone.utc).isoformat()
        if not isinstance(payload, dict):
            return
        if runtime == "ollama":
            models = payload.get("models")
            if not isinstance(models, list) or any(
                not isinstance(model, dict) or not isinstance(model.get("name"), str)
                or not model["name"] for model in models
            ):
                return
            unloaded = not models
        else:
            if (type(payload.get("schema_version")) is not int
                    or payload["schema_version"] != 1
                    or any(type(payload.get(key)) is not int or payload[key] < 0
                           for key in ("loaded_models", "queue_running", "queue_pending"))
                    or type(payload.get("cleanup_pending")) is not bool):
                return
            unloaded = payload["loaded_models"] == 0
            observation["cleanup_pending"] = payload["cleanup_pending"]
        observation.update(status="OBSERVED", models_unloaded=unloaded)

    def _dirty(self):
        self.marker.parent.mkdir(parents=True, exist_ok=True)
        with self.marker.open("w") as stream:
            stream.write("GPU ownership uncertain; verify workers stopped and both providers free before recovery.\n")
            stream.flush()
            os.fsync(stream.fileno())

    async def _json(self, client, path):
        runtime = ("ollama" if client is self.ollama and path == "/api/ps" else
                   "comfyui" if client is self.comfy and path == "/ai-platform/residency" else None)
        if runtime is not None:
            # Invalidate before awaiting: failures/cancellation cannot retain a
            # previous positive observation. Concurrent older reads cannot win.
            observation = {"status": "UNKNOWN", "observed_at": None,
                           "models_unloaded": None, "cleanup_pending": None}
            self._model_observations[runtime] = observation
        response = await client.get(path)
        response.raise_for_status()
        payload = response.json()
        if runtime is not None and self._model_observations[runtime] is observation:
            self._observe_models(runtime, payload, observation)
        return payload

    async def _idle(self):
        queue = await self._json(self.comfy, "/queue")
        if queue["queue_running"] != [] or queue["queue_pending"] != []:
            raise ResidencyError("ComfyUI is not idle")

    async def _comfy_models_idle(self):
        if not self.require_comfy_extension:
            return True  # Only quiesced legacy rollback after ComfyUI restart.
        evidence = await self._json(self.comfy, "/ai-platform/residency")
        self.cleanup_evidence = {**(self.cleanup_evidence or {}), "residency": evidence}
        if evidence.get("schema_version") != 1:
            raise ResidencyError("unsupported ComfyUI residency evidence")
        return (type(evidence.get("loaded_models")) is int
            and evidence["loaded_models"] == 0
            and evidence.get("cleanup_pending") is False
            and evidence.get("queue_running") == 0
            and evidence.get("queue_pending") == 0)

    async def enter_media(self):
        if self.state != "llm":
            raise ResidencyError("GPU residency requires recovery")
        try:
            if self.resume_comfy is not None:
                await self.resume_comfy()
            self._dirty()
            self.state = "draining_ollama"
            async with asyncio.timeout(self.timeout):
                await self._idle()
                while True:
                    models = (await self._json(self.ollama, "/api/ps"))["models"]
                    if not isinstance(models, list):
                        raise ResidencyError("invalid Ollama inventory")
                    if not models:
                        break
                    for model in models:
                        response = await self.ollama.post("/api/generate", json={
                            "model": model["name"], "keep_alive": 0, "stream": False})
                        response.raise_for_status()
                    await asyncio.sleep(self.poll)
                if not await self._comfy_models_idle():
                    raise ResidencyError("unexpected ComfyUI residency before media")
            self.state = "media"
        except BaseException:
            self.state = "blocked"
            raise

    async def leave_media(self):
        if self.state != "media":
            raise ResidencyError("GPU residency requires recovery")
        try:
            if self.resume_comfy is not None:
                await self.resume_comfy()
            self.state = "freeing_comfy"
            # Leave a read-only settling window between idempotent wakeups.
            # Re-posting on every poll can re-arm flags while the worker is
            # resetting caches/collecting, hiding its eventual clean state.
            loop = asyncio.get_running_loop()
            settle = min(2.0, self.timeout / 3)
            deadline = loop.time() + self.timeout
            async with asyncio.timeout(self.timeout):
                await self._idle()
                response = await self.comfy.post("/free", json={"unload_models": True, "free_memory": True})
                response.raise_for_status()
                next_wakeup = loop.time() + settle
                # /free only schedules cleanup. Verify allocator release, not
                # just the HTTP acknowledgement or an empty prompt queue.
                while True:
                    await self._idle()
                    devices = (await self._json(self.comfy, "/system_stats"))["devices"]
                    if not isinstance(devices, list) or not devices:
                        raise ResidencyError("missing ComfyUI memory evidence")
                    self.cleanup_evidence = {"reserved_bytes": [d.get("torch_vram_total") for d in devices],
                                             "idle_reserve_bytes": self.idle_reserve_bytes}
                    unloaded = await self._comfy_models_idle()
                    if unloaded and all(type(d["torch_vram_total"]) is int and 0 <= d["torch_vram_total"] <= self.idle_reserve_bytes for d in devices):
                        break
                    # A lost condition notification still needs a wakeup, but
                    # always observe again before sending it. The final window
                    # only observes: late clean evidence must meet the original
                    # deadline and every existing predicate, never a grace reset.
                    if loop.time() >= next_wakeup and loop.time() < deadline - settle:
                        response = await self.comfy.post("/free", json={"unload_models": True, "free_memory": True})
                        response.raise_for_status()
                        next_wakeup = loop.time() + settle
                    await asyncio.sleep(self.poll)
                await self._idle()
                if (await self._json(self.ollama, "/api/ps"))["models"] != []:
                    raise ResidencyError("Ollama reloaded outside Resource Manager")
            self.marker.unlink()
            self.state = "llm"
        except BaseException:
            self.state = "blocked"
            logging.getLogger(__name__).error("ComfyUI cleanup blocked: %s", self.cleanup_evidence)
            raise
