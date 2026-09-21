import asyncio
import json

import httpx
import pytest
from contextlib import asynccontextmanager

from ai_bridge.gateway.app import create_gateway_app
from ai_bridge.gateway.priority import PriorityClass, priority_for_class
from ai_bridge.settings import Settings


CLASSES = [
    ("infrastructure", 10),
    ("interactive-high", 25),
    ("interactive", 50),
    ("normal", 100),
    ("background", 200),
    ("maintenance", 300),
]
PATHS = [
    "/api/chat", "/api/generate", "/api/embed", "/api/embeddings",
    "/v1/chat/completions", "/v1/embeddings",
    "/clients/ventilation/api/chat", "/clients/hermes/v1/chat/completions",
    "/clients/hermes/v1/embeddings",
]


@pytest.fixture
def anyio_backend():
    return "asyncio"


@asynccontextmanager
async def api_client(app):
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            yield client


def make_app(handler=None, **settings):
    return create_gateway_app(
        Settings(_env_file=None, **settings),
        upstream_transport=httpx.MockTransport(
            handler or (lambda request: httpx.Response(200, json={"ok": True}))
        ),
    )


@pytest.mark.parametrize("name,number", CLASSES + [("critical", 10)])
def test_class_mapping(name, number):
    assert priority_for_class(name) == number
    assert [member.value for member in PriorityClass] == [name for name, _ in CLASSES]


@pytest.mark.parametrize("path", PATHS)
@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.anyio
async def test_all_scheduled_routes_consume_class_metadata(path, stream):
    seen = []

    def handler(request):
        seen.append(json.loads(request.content))
        async def content():
            yield b'{"ok":true}\n'
        return httpx.Response(200, content=content())

    async with api_client(make_app(handler)) as client:
        for name, number in CLASSES + [("critical", 10)]:
            response = await client.post(path, json={"priority_class": name, "stream": stream})
            assert response.status_code == 200
            assert response.headers["X-AI-Gateway-Priority"] == str(number)
            assert seen[-1] == {"stream": stream}
        assert (await client.get("/status")).json()["active_count"] == 0


@pytest.mark.parametrize("number", [-1000, -5, 0, 10, 25, 50, 73, 100, 200, 300, 1000])
@pytest.mark.anyio
async def test_legacy_numbers_keep_exact_value_and_override_class(number):
    async with api_client(make_app()) as client:
        for body in ({}, {"priority_class": "maintenance"}):
            response = await client.post("/api/chat", json=body, headers={"X-AI-Priority": str(number)})
            assert response.status_code == 200
            assert response.headers["X-AI-Gateway-Priority"] == str(number)
            lease = await client.post("/resource/leases", json={**body, "priority": number})
            assert lease.status_code == 201
            assert lease.json()["priority"] == number
            await client.delete(f"/resource/leases/{lease.json()['lease_id']}")


@pytest.mark.parametrize("value", [None, "", "Interactive", " interactive", "unknown", "ventilation", 10, True, [], {}])
@pytest.mark.anyio
async def test_invalid_class_rejected_before_admission_even_with_numeric_override(value):
    seen = []
    async with api_client(make_app(lambda request: seen.append(request))) as client:
        for path in ("/api/chat", "/resource/leases"):
            response = await client.post(path, json={"priority_class": value, "priority": 10}, headers={"X-AI-Priority": "10"})
            assert response.status_code == 400
            assert response.json() == {"detail": "invalid priority_class"}
        status = (await client.get("/status")).json()
        assert status["active_count"] == status["queued_count"] == 0
        assert status["resource_leases"]["lease_count"] == 0
        assert seen == []


@pytest.mark.parametrize("value", ["bad", "-1001", "1001"])
@pytest.mark.anyio
async def test_invalid_legacy_numeric_still_rejected_with_class(value):
    async with api_client(make_app()) as client:
        assert (await client.post("/api/chat", json={"priority_class": "normal"}, headers={"X-AI-Priority": value})).status_code == 400
        assert (await client.post("/resource/leases", json={"priority_class": "normal", "priority": value})).status_code == 400


@pytest.mark.anyio
async def test_legacy_defaults_and_body_bytes_are_preserved():
    seen = []

    def handler(request):
        seen.append(request.content)
        return httpx.Response(200, json={})

    async with api_client(make_app(handler, gateway_priority_ventilation=12, gateway_priority_interactive=55, gateway_priority_normal=101)) as client:
        for path, expected in [("/clients/ventilation/api/chat", 12), ("/api/chat", 101), ("/v1/chat/completions", 55)]:
            body = b'{ "messages": [], "stream": false }'
            response = await client.post(path, content=body)
            assert response.headers["X-AI-Gateway-Priority"] == str(expected)
            assert seen[-1] == body
        lease = (await client.post("/resource/leases", json={})).json()
        assert lease["priority"] == 55
        await client.delete(f"/resource/leases/{lease['lease_id']}")
        response = await client.post("/clients/ventilation/api/chat", json={"priority_class": "infrastructure"})
        assert response.headers["X-AI-Gateway-Priority"] == "10"


def test_classes_and_legacy_requests_share_order_and_fifo_without_prompt_status(caplog):
    async def run():
        calls = []

        async def handler(request):
            calls.append(json.loads(request.content)["label"])
            return httpx.Response(200, json={})

        app = make_app(handler, gateway_max_queue_size=32)
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                blocker = await app.state.scheduler.acquire(priority=1000, source="block")
                tasks = []
                expected = []
                for name, number in reversed(CLASSES):
                    for suffix in ("a", "legacy", "b"):
                        label = f"{name}-{suffix}"
                        body = {"label": label, "prompt": "private-prompt-marker"}
                        headers = {}
                        if suffix == "legacy":
                            headers["X-AI-Priority"] = str(number)
                        else:
                            body["priority_class"] = name
                        tasks.append(asyncio.create_task(client.post("/api/chat", json=body, headers=headers)))
                        await asyncio.sleep(0)
                        expected.append((number, label))
                status = (await client.get("/status")).json()
                assert status["queued_count"] == 18
                assert "private-prompt-marker" not in json.dumps(status)
                assert calls == []  # no preemption
                await app.state.scheduler.release(blocker)
                responses = await asyncio.wait_for(asyncio.gather(*tasks), 5)
                assert all(response.status_code == 200 for response in responses)
                assert calls == [label for _, label in sorted(expected, key=lambda item: item[0])]
                assert (await client.get("/status")).json()["active_count"] == 0
    asyncio.run(run())
    assert "private-prompt-marker" not in caplog.text


@pytest.mark.anyio
async def test_class_leases_order_fifo_and_existing_lease_priority_wins():
    async with api_client(make_app(gateway_max_queue_size=32)) as client:
        blocker = (await client.post("/resource/leases", json={"priority": 1000})).json()
        leases = []
        for name, number in reversed(CLASSES):
            for _ in range(2):
                response = await client.post("/resource/leases", json={"priority_class": name})
                assert response.status_code == 201
                lease = response.json()
                assert lease["priority"] == number
                assert lease["state"] == "queued"
                leases.append(lease)
        await client.delete(f"/resource/leases/{blocker['lease_id']}")
        for lease in sorted(leases, key=lambda lease: lease["priority"]):
            assert (await client.get(f"/resource/leases/{lease['lease_id']}")).json()["state"] == "active"
            response = await client.post("/api/chat", json={"priority_class": "maintenance"}, headers={"X-AI-Resource-Lease": lease["lease_id"], "X-AI-Priority": "-1000"})
            assert response.headers["X-AI-Gateway-Priority"] == str(lease["priority"])
            await client.delete(f"/resource/leases/{lease['lease_id']}")
        assert (await client.get("/status")).json()["active_count"] == 0
