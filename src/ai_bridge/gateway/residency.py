"""Verified shared-GPU residency transitions. Queue ownership outlives failures."""
from __future__ import annotations

import asyncio
import os
from pathlib import Path

import httpx


class ResidencyError(RuntimeError):
    pass


class GPUResidency:
    def __init__(self, ollama: httpx.AsyncClient, comfy: httpx.AsyncClient,
                 marker: Path, *, timeout: float = 90, poll: float = .25):
        self.ollama, self.comfy = ollama, comfy
        self.marker, self.timeout, self.poll = marker, timeout, poll
        self.state = "blocked" if marker.exists() else "llm"

    def snapshot(self):
        return {"state": self.state, "recovery_required": self.state == "blocked"}

    def _dirty(self):
        self.marker.parent.mkdir(parents=True, exist_ok=True)
        with self.marker.open("w") as stream:
            stream.write("GPU ownership uncertain; verify workers stopped and both providers free before recovery.\n")
            stream.flush()
            os.fsync(stream.fileno())

    async def _json(self, client, path):
        response = await client.get(path)
        response.raise_for_status()
        return response.json()

    async def _idle(self):
        queue = await self._json(self.comfy, "/queue")
        if queue["queue_running"] != [] or queue["queue_pending"] != []:
            raise ResidencyError("ComfyUI is not idle")

    async def enter_media(self):
        if self.state != "llm":
            raise ResidencyError("GPU residency requires recovery")
        try:
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
            self.state = "media"
        except BaseException:
            self.state = "blocked"
            raise

    async def leave_media(self):
        if self.state != "media":
            raise ResidencyError("GPU residency requires recovery")
        try:
            self.state = "freeing_comfy"
            async with asyncio.timeout(self.timeout):
                await self._idle()
                response = await self.comfy.post("/free", json={"unload_models": True, "free_memory": True})
                response.raise_for_status()
                # /free only schedules cleanup. Verify allocator release, not
                # just the HTTP acknowledgement or an empty prompt queue.
                while True:
                    await self._idle()
                    devices = (await self._json(self.comfy, "/system_stats"))["devices"]
                    if not isinstance(devices, list) or not devices:
                        raise ResidencyError("missing ComfyUI memory evidence")
                    if all(type(d["torch_vram_total"]) is int and d["torch_vram_total"] == 0 for d in devices):
                        break
                    await asyncio.sleep(self.poll)
                await self._idle()
            self.marker.unlink()
            self.state = "llm"
        except BaseException:
            self.state = "blocked"
            raise
