"""Granite v3 preview is opt-in, read-only and fail-closed."""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest

from ai_bridge.decision_router import (
    RouterContractError, RouterDecision, parse_router_decision, validate_input,
)
from ai_bridge.gateway.app import create_gateway_app
from ai_bridge.gateway import granite_preview
from ai_bridge.settings import Settings


def route(name):
    mapping = {
        "knowledge_rag": ["knowledge.search"], "reasoning": [],
        "telemetry": ["telemetry.read"], "graphify": ["graphify.query"],
        "vision": ["vision.analyze"], "tool": ["agent.ers"],
    }
    return {"decision": "route", "route": name, "selected_tools": mapping[name],
            "required_capability": None}


@pytest.mark.parametrize("name", [
    "knowledge_rag", "reasoning", "telemetry", "graphify", "vision", "tool",
])
def test_contract_supported_routes(name):
    assert parse_router_decision(json.dumps(route(name))).as_dict() == route(name)


@pytest.mark.parametrize("payload", [
    {"decision":"route","route":"tool","selected_tools":["github.write"],"required_capability":None},
    {"decision":"route","route":"reasoning","selected_tools":["agent.ers"],"required_capability":None},
    {"decision":"route","route":["vision"],"selected_tools":["vision.analyze"],"required_capability":None},
    {"decision":"clarify","route":None,"selected_tools":["vision.analyze"],"required_capability":None},
    {"decision":"fallback","route":None,"selected_tools":[],"required_capability":None},
    {"decision":"fallback","route":None,"selected_tools":[],"required_capability":"shell.execute"},
    {"decision":"no_action","route":"reasoning","selected_tools":[],"required_capability":None},
    {"decision":"no_action","route":None,"selected_tools":[],"required_capability":None,"extra":1},
])
def test_contract_rejects_unsafe_model_output(payload):
    with pytest.raises(RouterContractError):
        parse_router_decision(payload)


@pytest.mark.parametrize("text", [
    "", "  ", "password: my-password", "Bearer secret-auth", "\x00hello",
])
def test_input_filter_fails_closed(text):
    with pytest.raises(RouterContractError):
        validate_input(text)


def test_disabled_endpoint_does_not_call_backend():
    class Never:
        async def decide(self, text):
            pytest.fail("disabled Granite was invoked")
    async def scenario():
        app = create_gateway_app(
            Settings(router_preview_enabled=False),
            upstream_transport=httpx.MockTransport(
                lambda req: httpx.Response(200, json={"models":[]})
            ),
            granite_router_backend=Never(),
        )
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app,client=("127.0.0.1",313)),
                base_url="http://test",
            ) as client:
                response=await client.post(
                    "/api/v1/router/preview",
                    json={"text":"Check technical details in the internal documents."},
                )
                assert response.status_code==404
                assert response.json()["error"]["code"]=="router_preview_disabled"
    asyncio.run(scenario())


def test_enabled_endpoint_is_read_only_and_never_exposes_model_text():
    class Stub:
        async def decide(self, text):
            assert text=="Inspect the new drawing and describe pin numbering."
            return parse_router_decision(route("vision"))
    async def scenario():
        app=create_gateway_app(
            Settings(router_preview_enabled=True),
            upstream_transport=httpx.MockTransport(
                lambda req: httpx.Response(200,json={"models":[]})
            ),
            granite_router_backend=Stub(),
        )
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app,client=("127.0.0.1",313)),
                base_url="http://test",
            ) as client:
                response=await client.post("/api/v1/router/preview",
                    json={"text":"Inspect the new drawing and describe pin numbering."})
                assert response.status_code==200,response.text
                data=response.json()
                assert data["mode"]=="read_only"
                assert data["decision"]==route("vision")
                assert data["executes_tools"] is False
                assert data["authorizes_tools"] is False
                assert data["modifies_production_response"] is False
                assert "Inspect the new drawing" not in response.text
    asyncio.run(scenario())


def test_backend_exclusive_ticket_unload_and_no_tool_execution(monkeypatch):
    class Scheduler:
        admission_blocked=False
        released=[]
        async def snapshot(self):
            return {"active_count":0,"queued_count":0}
        async def acquire(self,**kwargs):
            assert kwargs["source"]=="granite-router-preview"
            return SimpleNamespace(job_id="test")
        async def release(self,ticket,**kwargs):
            self.released.append(kwargs["state"])
    class Residency:
        state="llm"
        def _dirty(self):
            pytest.fail("unexpected dirty marker")
    seen=[]
    def handler(req):
        seen.append(req.url.path)
        if req.url.path=="/api/chat":
            payload=json.loads(req.content)
            assert payload["model"]=="granite-router-v3:dev"
            assert payload["messages"][1]["content"]=="Retrieve technical information about CAN."
            assert "tools" not in payload
            return httpx.Response(200,json={"message":{"content":json.dumps(route("knowledge_rag"))}})
        if req.url.path=="/api/generate":
            return httpx.Response(200,json={"done":True})
        if req.url.path=="/api/ps":
            return httpx.Response(200,json={"models":[]})
        pytest.fail("unexpected upstream path")
    orig=httpx.AsyncClient
    monkeypatch.setattr(granite_preview.httpx,"AsyncClient",
        lambda **kwargs: orig(**{**kwargs,"transport":httpx.MockTransport(handler)}))
    async def scenario():
        scheduler=Scheduler()
        backend=granite_preview.GranitePreviewBackend(scheduler,Residency(),
            rtx_url="http://127.0.0.1:11436",model="granite-router-v3:dev")
        result=await backend.decide("Retrieve technical information about CAN.")
        assert result.as_dict()==route("knowledge_rag")
        assert [str(item) for item in scheduler.released]==["completed"]
        assert seen==["/api/chat","/api/generate","/api/ps"]
    asyncio.run(scenario())


def test_backend_unload_failure_fences_rm(monkeypatch):
    class Scheduler:
        admission_blocked=False
        released=False
        async def snapshot(self):
            return {"active_count":0,"queued_count":0}
        async def acquire(self,**kwargs):
            return SimpleNamespace(job_id="fence")
        async def release(self,*args,**kwargs):
            self.released=True
    class Residency:
        state="llm"
        dirty=False
        def _dirty(self):
            self.dirty=True
    def handler(req):
        if req.url.path=="/api/chat":
            return httpx.Response(200,json={"message":{"content":json.dumps(route("reasoning"))}})
        if req.url.path=="/api/generate":
            return httpx.Response(503)
        pytest.fail("unload attempted unexpected path")
    original=httpx.AsyncClient
    monkeypatch.setattr(granite_preview.httpx,"AsyncClient",
        lambda **kwargs: original(**{**kwargs,"transport":httpx.MockTransport(handler)}))
    async def scenario():
        scheduler,residency=Scheduler(),Residency()
        backend=granite_preview.GranitePreviewBackend(scheduler,residency,
            rtx_url="http://127.0.0.1:11436",model="granite-router-v3:dev")
        with pytest.raises(RuntimeError,match="router_gpu_cleanup_unverified"):
            await backend.decide("Explain using the facts in this question.")
        assert scheduler.admission_blocked is True
        assert scheduler.released is False
        assert residency.state=="blocked" and residency.dirty is True
    asyncio.run(scenario())


def test_bad_model_tool_mapping_is_rejected_before_any_execution(monkeypatch):
    class Scheduler:
        admission_blocked=False
        released=[]
        async def snapshot(self):
            return {"active_count":0,"queued_count":0}
        async def acquire(self,**kwargs):
            return SimpleNamespace(job_id="bad")
        async def release(self,*args,**kwargs):
            self.released.append(str(kwargs["state"]))
    class Residency:
        state="llm"
        def _dirty(self):
            pytest.fail("GPU cleaned, no fence needed")
    def handler(req):
        if req.url.path=="/api/chat":
            unsafe={"decision":"route","route":"tool",
                    "selected_tools":["github.write"],"required_capability":None}
            return httpx.Response(200,json={"message":{"content":json.dumps(unsafe)}})
        if req.url.path=="/api/generate":
            return httpx.Response(200,json={"done":True})
        if req.url.path=="/api/ps":
            return httpx.Response(200,json={"models":[]})
        pytest.fail("unexpected tool execution")
    original=httpx.AsyncClient
    monkeypatch.setattr(granite_preview.httpx,"AsyncClient",
        lambda **kwargs: original(**{**kwargs,"transport":httpx.MockTransport(handler)}))
    async def scenario():
        scheduler=Scheduler()
        backend=granite_preview.GranitePreviewBackend(scheduler,Residency(),
            rtx_url="http://127.0.0.1:11436",model="granite-router-v3:dev")
        with pytest.raises(RouterContractError):
            await backend.decide("Update our project documentation in GitHub.")
        assert scheduler.released==["failed"]
    asyncio.run(scenario())
