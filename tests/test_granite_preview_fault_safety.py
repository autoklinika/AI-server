"""DEV regression: Granite router errors must never execute tools or leak GPU leases."""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest

from ai_bridge.decision_router import RouterContractError
from ai_bridge.gateway.granite_preview import GranitePreviewBackend, GranitePreviewBusy
from ai_bridge.gateway import granite_preview


def test_preview_busy_resource_manager_rejects_without_ollama(monkeypatch):
    class Scheduler:
        admission_blocked = False
        acquire_count = 0

        async def snapshot(self):
            return {"active_count": 1, "queued_count": 0}

        async def acquire(self, **kwargs):
            self.acquire_count += 1
            pytest.fail("Must not request RTX while RM is busy")

    class Residency:
        state = "llm"

    def fail_client(**kwargs):
        pytest.fail("Must not create an upstream client while RM busy")

    monkeypatch.setattr(granite_preview.httpx, "AsyncClient", fail_client)

    async def scenario():
        sched = Scheduler()
        preview = GranitePreviewBackend(sched, Residency(),
            rtx_url="http://127.0.0.1:11436", model="granite-router-v4-tpl1:dev")
        with pytest.raises(GranitePreviewBusy):
            await preview.decide("Read the latest WVC analysis.")
        assert sched.acquire_count == 0

    asyncio.run(scenario())


@pytest.mark.parametrize("fault,expected_error", [
    ("invalid_json", RouterContractError),
    ("missing_json_fields", RouterContractError),
    ("wrong_capability", RouterContractError),
    ("ollama_http_503", httpx.HTTPStatusError),
    ("missing_message", KeyError),
])
def test_preview_fail_closed_releases_verified_rm_ticket(monkeypatch, fault, expected_error):
    class Scheduler:
        admission_blocked = False
        acquired = 0
        released = []

        async def snapshot(self):
            return {"active_count": 0, "queued_count": 0}

        async def acquire(self, **kwargs):
            self.acquired += 1
            return SimpleNamespace(job_id="fault-test", lease_id="mock")

        async def release(self, ticket, **kwargs):
            self.released.append((ticket.lease_id, str(kwargs["state"])))

    class Residency:
        state = "llm"

        def _dirty(self):
            pytest.fail("Unload succeeded, no dirty fence needed")

    calls = []

    def handler(req):
        calls.append(req.url.path)
        if req.url.path == "/api/chat":
            request = json.loads(req.content)
            assert "format" not in request
            assert "tools" not in request
            assert request["model"] == "granite-router-v4-tpl1:dev"
            if fault == "ollama_http_503":
                return httpx.Response(503)
            if fault == "missing_message":
                return httpx.Response(200, json={"other_field": {}})
            if fault == "invalid_json":
                raw = "{garbled"
            elif fault == "missing_json_fields":
                raw = '{"decision":"route"}'
            else:
                raw = json.dumps({
                    "decision": "route", "route": "tool",
                    "selected_tools": ["agent.ers"],
                    "required_capability": "host.inspect",
                })
            return httpx.Response(200, json={"message": {"content": raw}})
        if req.url.path == "/api/generate":
            return httpx.Response(200, json={"done": True})
        if req.url.path == "/api/ps":
            return httpx.Response(200, json={"models": []})
        pytest.fail(f"Unexpected upstream or tool call {req.url.path}")

    original = httpx.AsyncClient
    monkeypatch.setattr(granite_preview.httpx, "AsyncClient",
        lambda **kwargs: original(**{**kwargs, "transport": httpx.MockTransport(handler)}))

    async def scenario():
        sched = Scheduler()
        preview = GranitePreviewBackend(sched, Residency(),
            rtx_url="http://127.0.0.1:11436",
            model="granite-router-v4-tpl1:dev")
        with pytest.raises(expected_error):
            await preview.decide("Use only the allowed diagnostic tools.")
        assert sched.acquired == 1
        assert sched.released == [("mock", "failed")]
        assert calls == ["/api/chat", "/api/generate", "/api/ps"]
        assert sched.admission_blocked is False

    asyncio.run(scenario())
