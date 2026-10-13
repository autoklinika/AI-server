"""Verified shared-GPU residency transitions. Queue ownership outlives failures."""
from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path

import httpx

from .vision_residency_evidence import gpu_vram_used_bytes, worker_birth_ticks, worker_cgroup_path, scoped_processes


class ResidencyError(RuntimeError):
    pass


class GPUResidency:
    def __init__(self, ollama: httpx.AsyncClient, comfy: httpx.AsyncClient,
                 marker: Path, *, timeout: float = 90, poll: float = .25, idle_reserve_bytes: int = 0,
                 require_comfy_extension: bool = True, resume_comfy=None,
                 vision_process_probe=worker_birth_ticks, vision_memory_probe=gpu_vram_used_bytes,
                 vision_scope_probe=worker_cgroup_path, vision_cgroup_members=scoped_processes,
                 vision_memory_tolerance_bytes: int = 64 * 1024 * 1024):
        self.ollama, self.comfy = ollama, comfy
        self.marker, self.timeout, self.poll = marker, timeout, poll
        self.idle_reserve_bytes = idle_reserve_bytes
        self.require_comfy_extension = require_comfy_extension
        self.resume_comfy = resume_comfy
        self.state = "blocked" if marker.exists() else "llm"
        self.cleanup_evidence = None
        self.vision_process_probe = vision_process_probe
        self.vision_memory_probe = vision_memory_probe
        self.vision_scope_probe = vision_scope_probe
        self.vision_cgroup_members = vision_cgroup_members
        self._vision_scope_path: str | None = None
        self.vision_memory_tolerance_bytes = vision_memory_tolerance_bytes
        self._vision_worker: tuple[int, int] | None = None
        self._vision_baseline_bytes: int | None = None

    def snapshot(self):
        return {"state": self.state, "recovery_required": self.state == "blocked",
                "cleanup_evidence": self.cleanup_evidence}

    def _dirty(self):
        self.marker.parent.mkdir(parents=True, exist_ok=True)
        with self.marker.open("w") as stream:
            stream.write("GPU ownership uncertain; verify workers stopped and both providers free before recovery.\n")
            stream.flush()
            os.fsync(stream.fileno())

    def fail_closed(self) -> None:
        """Persist uncertainty before any previously admitted GPU slot could reopen.

        Used if an exception interrupts a resource transition after ownership
        was pinned, including an early exception before enter_vision wrote it.
        """
        self.state = "blocked"
        self._dirty()

    async def _json(self, client, path):
        response = await client.get(path)
        response.raise_for_status()
        return response.json()

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


    async def enter_vision(self, worker_pid: int, scope_path: str) -> None:
        """Pin the shared GPU before a declared, *parked* Vision worker may run.

        External executor must start the worker WAITING for an ownership token.
        The worker may run GPU kernels only after authorization is returned.
        """
        if self.state != "llm":
            raise ResidencyError("GPU residency requires recovery")
        birth = self.vision_process_probe(worker_pid)
        if birth is None or birth <= 0:
            raise ResidencyError("Vision process identity unavailable")
        if not isinstance(scope_path, str) or self.vision_scope_probe(worker_pid) != scope_path:
            raise ResidencyError("Vision worker must be in a trusted dedicated cgroup scope")
        members = self.vision_cgroup_members(scope_path)
        if members is None or worker_pid not in members:
            raise ResidencyError("Vision worker is not present in declared cgroup")
        self._vision_scope_path = scope_path
        self._vision_worker = (worker_pid, birth)
        self._vision_baseline_bytes = None
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
                    raise ResidencyError("ComfyUI residency not idle before Vision")
                if (self.vision_process_probe(worker_pid) != birth
                    or self.vision_scope_probe(worker_pid) != scope_path
                    or worker_pid not in (self.vision_cgroup_members(scope_path) or set())):
                    raise ResidencyError("Vision scope/worker identity changed before admission")
                # Baseline AFTER verified Ollama drain and Comfy idle, never
                # include Ollama's old weights in the allowed cleanup ceiling.
                baseline = self.vision_memory_probe()
                if baseline is None or baseline < 0:
                    raise ResidencyError("Vision GPU memory baseline unavailable")
                self._vision_baseline_bytes = baseline
            self.state = "vision"
        except BaseException:
            self.state = "blocked"
            raise

    async def leave_vision(self) -> None:
        """Release GPU ONLY after process exit plus authoritative memory evidence.

        Missing/dirty cleanup evidence permanently retains the blocked marker.
        A successful HTTP response or worker-supplied boolean is never proof.
        """
        if (self.state != "vision" or self._vision_worker is None
                or self._vision_baseline_bytes is None or self._vision_scope_path is None):
            raise ResidencyError("Vision GPU residency requires recovery")
        worker_pid, _birth = self._vision_worker
        try:
            self.state = "checking_vision_cleanup"
            async with asyncio.timeout(self.timeout):
                if self.vision_process_probe(worker_pid) is not None:
                    raise ResidencyError("Vision worker still alive; GPU ownership cannot release")
                # cgroup v2 scope proves no descendants or processes that left
                # the parent's process group may still hold GPU allocations.
                members = self.vision_cgroup_members(self._vision_scope_path)
                if members is None or members:
                    raise ResidencyError("Vision cgroup not empty or evidence unavailable")
                await self._idle()
                if not await self._comfy_models_idle():
                    raise ResidencyError("ComfyUI not idle after Vision")
                if (await self._json(self.ollama, "/api/ps"))["models"] != []:
                    raise ResidencyError("Ollama reloaded during Vision execution")
                used = self.vision_memory_probe()
                if used is None or used < 0 or used > self._vision_baseline_bytes + self.vision_memory_tolerance_bytes:
                    raise ResidencyError("Vision GPU memory not returned to baseline")
                self.cleanup_evidence = {"vision_worker_exited": True,
                                         "gpu_memory_baseline_bytes": self._vision_baseline_bytes,
                                         "gpu_memory_final_bytes": used,
                                         "gpu_memory_tolerance_bytes": self.vision_memory_tolerance_bytes}
            self.marker.unlink()
            self._vision_worker = None
            self._vision_scope_path = None
            self._vision_baseline_bytes = None
            self.state = "llm"
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
