import asyncio

import pytest
from starlette.requests import Request

from ai_bridge.platform.api import _generate_until_disconnect
from ai_bridge.providers.contracts import LLMRequest, LLMResponse


class ImmediateProvider:
    async def generate(self, request):
        return LLMResponse(request_id=request.request_id, content="ok")


class BlockingProvider:
    def __init__(self):
        self.cancelled = False

    async def generate(self, _request):
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.cancelled = True
            raise


def llm_request():
    return LLMRequest(
        request_id="req-disconnect",
        capability="structured-generation",
        messages=[{"role": "user", "content": "test"}],
        response_schema={"type": "object"},
    )


def asgi_request(events):
    queue = asyncio.Queue()
    for event in events:
        queue.put_nowait(event)

    async def receive():
        return await queue.get()

    return Request(
        {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": "/api/v1/knowledge/ask",
            "raw_path": b"/api/v1/knowledge/ask",
            "query_string": b"",
            "headers": [],
            "client": ("127.0.0.1", 12345),
            "server": ("127.0.0.1", 11435),
        },
        receive=receive,
    )


def test_completed_generation_cancels_blocked_receive_watcher():
    async def run():
        request = asgi_request([])
        result = await asyncio.wait_for(
            _generate_until_disconnect(
                ImmediateProvider(),
                llm_request(),
                request,
            ),
            timeout=0.5,
        )
        assert result.content == "ok"

    asyncio.run(run())


def test_raw_asgi_disconnect_cancels_provider_generation():
    async def run():
        provider = BlockingProvider()
        request = asgi_request([
            {"type": "http.request", "body": b"", "more_body": False},
            {"type": "http.disconnect"},
        ])
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(
                _generate_until_disconnect(
                    provider,
                    llm_request(),
                    request,
                ),
                timeout=1.0,
            )
        assert provider.cancelled is True

    asyncio.run(run())
