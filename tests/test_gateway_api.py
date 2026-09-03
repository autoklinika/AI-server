import asyncio
import json

import httpx

from ai_bridge.gateway.app import create_gateway_app
from ai_bridge.settings import Settings


def _settings(**overrides) -> Settings:
    values = {
        "ollama_url": "http://ollama.local",
        "gateway_max_concurrency": 1,
        "gateway_max_queue_size": 8,
        "gateway_connect_timeout_seconds": 1.0,
        "gateway_upstream_timeout_seconds": 10.0,
        "gateway_health_timeout_seconds": 1.0,
        "gateway_priority_ventilation": 10,
        "gateway_priority_normal": 100,
        "gateway_priority_interactive": 50,
    }
    values.update(overrides)
    return Settings(**values)


def test_gateway_sends_higher_priority_waiter_first() -> None:
    async def run() -> None:
        calls: list[str] = []
        block_started = asyncio.Event()
        release_block = asyncio.Event()

        async def handler(request: httpx.Request) -> httpx.Response:
            payload = json.loads(request.content)
            label = payload["label"]
            calls.append(label)
            if label == "block":
                block_started.set()
                await release_block.wait()
            return httpx.Response(200, json={"label": label})

        app = create_gateway_app(
            _settings(),
            upstream_transport=httpx.MockTransport(handler),
        )
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://gateway",
            ) as client:
                block = asyncio.create_task(
                    client.post("/api/chat", json={"label": "block"})
                )
                await asyncio.wait_for(block_started.wait(), 1)
                low = asyncio.create_task(
                    client.post(
                        "/api/chat",
                        json={"label": "low"},
                        headers={"X-AI-Priority": "200"},
                    )
                )
                await asyncio.sleep(0)
                high = asyncio.create_task(
                    client.post(
                        "/api/chat",
                        json={"label": "high"},
                        headers={"X-AI-Priority": "10"},
                    )
                )
                await asyncio.sleep(0)
                release_block.set()
                responses = await asyncio.gather(block, low, high)

                assert all(response.status_code == 200 for response in responses)
                assert calls == ["block", "high", "low"]
                assert high.result().headers["x-ai-gateway-priority"] == "10"

    asyncio.run(run())


def test_ventilation_namespace_defaults_to_priority_10_and_native_ollama_path() -> None:
    async def run() -> None:
        seen_paths: list[str] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            seen_paths.append(request.url.path)
            return httpx.Response(200, json={"ok": True})

        app = create_gateway_app(
            _settings(),
            upstream_transport=httpx.MockTransport(handler),
        )
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://gateway",
            ) as client:
                tags = await client.get("/clients/ventilation/api/tags")
                response = await client.post(
                    "/clients/ventilation/api/chat",
                    json={"stream": False},
                )
                assert tags.status_code == 200
                assert response.status_code == 200
                assert response.headers["x-ai-gateway-priority"] == "10"
                assert seen_paths == ["/api/tags", "/api/chat"]

    asyncio.run(run())


def test_openai_chat_defaults_to_interactive_priority() -> None:
    async def run() -> None:
        async def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"ok": True})

        app = create_gateway_app(
            _settings(),
            upstream_transport=httpx.MockTransport(handler),
        )
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://gateway",
            ) as client:
                response = await client.post(
                    "/v1/chat/completions",
                    json={"stream": False},
                )
                assert response.status_code == 200
                assert response.headers["x-ai-gateway-priority"] == "50"

    asyncio.run(run())


def test_invalid_priority_is_rejected_before_upstream() -> None:
    async def run() -> None:
        calls = 0

        async def handler(_request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            return httpx.Response(200, json={"ok": True})

        app = create_gateway_app(
            _settings(),
            upstream_transport=httpx.MockTransport(handler),
        )
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://gateway",
            ) as client:
                response = await client.post(
                    "/api/chat",
                    json={},
                    headers={"X-AI-Priority": "bad"},
                )
                assert response.status_code == 400
                assert calls == 0

    asyncio.run(run())


def test_streaming_request_holds_slot_until_stream_finishes() -> None:
    async def run() -> None:
        calls: list[str] = []
        stream_started = asyncio.Event()
        release_stream = asyncio.Event()

        async def handler(request: httpx.Request) -> httpx.Response:
            payload = json.loads(request.content)
            label = payload["label"]
            calls.append(label)
            if label == "stream":

                async def content():
                    stream_started.set()
                    yield b'{"part":1}\n'
                    await release_stream.wait()
                    yield b'{"part":2}\n'

                return httpx.Response(
                    200,
                    content=content(),
                    headers={"content-type": "application/x-ndjson"},
                )
            return httpx.Response(200, json={"label": label})

        app = create_gateway_app(
            _settings(),
            upstream_transport=httpx.MockTransport(handler),
        )
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://gateway",
            ) as client:
                first = asyncio.create_task(
                    client.post(
                        "/api/chat",
                        json={"label": "stream", "stream": True},
                    )
                )
                await asyncio.wait_for(stream_started.wait(), 1)
                second = asyncio.create_task(
                    client.post(
                        "/api/chat",
                        json={"label": "second", "stream": False},
                    )
                )
                await asyncio.sleep(0.05)
                assert calls == ["stream"]

                release_stream.set()
                await asyncio.gather(first, second)
                assert calls == ["stream", "second"]

    asyncio.run(run())
