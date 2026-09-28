import asyncio

import pytest

from ai_bridge.platform.api import _generate_until_disconnect
from ai_bridge.providers.contracts import LLMRequest, LLMResponse


class NeverDisconnect:
    async def is_disconnected(self):
        return False


class DisconnectAfterProbe:
    def __init__(self):
        self.calls = 0

    async def is_disconnected(self):
        self.calls += 1
        return self.calls >= 2


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


def request():
    return LLMRequest(
        request_id="req-disconnect",
        capability="structured-generation",
        messages=[{"role": "user", "content": "test"}],
        response_schema={"type": "object"},
    )


def test_completed_generation_does_not_hang_disconnect_watcher():
    async def run():
        result = await asyncio.wait_for(
            _generate_until_disconnect(
                ImmediateProvider(),
                request(),
                NeverDisconnect(),
            ),
            timeout=0.5,
        )
        assert result.content == "ok"

    asyncio.run(run())


def test_client_disconnect_cancels_provider_generation():
    async def run():
        provider = BlockingProvider()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(
                _generate_until_disconnect(
                    provider,
                    request(),
                    DisconnectAfterProbe(),
                ),
                timeout=1.0,
            )
        assert provider.cancelled is True

    asyncio.run(run())
