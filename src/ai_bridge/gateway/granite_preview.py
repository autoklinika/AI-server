"""On-demand RTX Granite preview. One existing RM ticket, no background process.

This does NOT change the production router, response or tool permissions.
Missing GPU unload proof intentionally blocks RM admission for operator recovery.
"""
from __future__ import annotations

import asyncio
import json

import httpx

from ai_bridge.decision_router import (
    DECISION_SCHEMA, ROUTER_PROMPT, RouterContractError,
    RouterDecision, parse_router_decision, validate_input,
)
from .jobs import JobLifecycle, JobMetadata


class GranitePreviewBusy(Exception):
    """RM is not idle or the GPU is in another lifecycle state."""


class GranitePreviewBackend:
    def __init__(self, scheduler, residency, *, rtx_url: str, model: str):
        self.scheduler = scheduler
        self.residency = residency
        self.rtx_url = rtx_url
        self.model = model

    async def _unload(self, client: httpx.AsyncClient) -> bool:
        """Unload *only* the preview model. Verify RTX /api/ps before RM release."""
        try:
            response = await client.post("/api/generate", json={
                "model": self.model, "keep_alive": 0, "stream": False,
            }, timeout=8)
            response.raise_for_status()
            for _ in range(20):
                current = await client.get("/api/ps", timeout=2)
                current.raise_for_status()
                models = current.json().get("models")
                if isinstance(models, list) and all(
                    isinstance(item, dict) and item.get("name") != self.model
                    for item in models
                ):
                    return True
                await asyncio.sleep(0.2)
        except (httpx.HTTPError, ValueError, TypeError):
            pass
        return False

    async def decide(self, text: str) -> RouterDecision:
        validate_input(text)
        # No queues or competing dispatches: Granite preview is opportunistic.
        if self.scheduler.admission_blocked or self.residency.state != "llm":
            raise GranitePreviewBusy()
        snapshot = await self.scheduler.snapshot()
        if snapshot["active_count"] or snapshot["queued_count"]:
            raise GranitePreviewBusy()

        async with httpx.AsyncClient(
            base_url=self.rtx_url.rstrip("/"),
            trust_env=False, timeout=httpx.Timeout(25.0, connect=4.0),
        ) as client:
            ticket = None
            dispatched = False
            complete = False
            try:
                try:
                    ticket = await asyncio.wait_for(
                        self.scheduler.acquire(
                            priority=200, source="granite-router-preview",
                            metadata=JobMetadata(
                                capability="chat", domain="shared",
                            ),
                        ),
                        timeout=0.20,
                    )
                except asyncio.TimeoutError:
                    raise GranitePreviewBusy() from None

                if self.scheduler.admission_blocked or self.residency.state != "llm":
                    raise GranitePreviewBusy()
                # No user-supplied model tag, endpoint or tool parameters.
                dispatched = True
                reply = await client.post("/api/chat", json={
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": ROUTER_PROMPT},
                        {"role": "user", "content": text},
                    ],
                    "format": DECISION_SCHEMA,
                    "think": False,
                    "stream": False,
                    "options": {"temperature": 0, "num_ctx": 2048,
                                "num_predict": 128},
                    "keep_alive": "30s",
                }, timeout=23)
                reply.raise_for_status()
                content = reply.json()["message"]["content"]
                if not isinstance(content, str):
                    raise RouterContractError("router_empty_response")
                outcome = parse_router_decision(content)
                complete = True
                return outcome
            finally:
                if ticket is not None:
                    # Never release admission while the CUDA model remains resident.
                    try:
                        # Cancelled requests cannot silently release a live GPU.
                        safe = not dispatched or await asyncio.shield(
                            asyncio.wait_for(self._unload(client), timeout=15)
                        )
                    except BaseException:
                        safe = False
                    if safe:
                        await self.scheduler.release(
                            ticket, state=(
                                JobLifecycle.COMPLETED if complete
                                else JobLifecycle.FAILED
                            ),
                        )
                    else:
                        self.scheduler.admission_blocked = True
                        self.residency.state = "blocked"
                        self.residency._dirty()
                        raise RuntimeError("router_gpu_cleanup_unverified")
