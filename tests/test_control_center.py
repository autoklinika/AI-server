import asyncio

import httpx
from fastapi.testclient import TestClient

from ai_bridge.control_center.app import create_control_center_app


def test_control_center_serves_shell_and_pwa_assets():
    client = TestClient(create_control_center_app())

    shell = client.get("/")
    assert shell.status_code == 200
    assert "AI Control Center" in shell.text
    assert "/control/assets/app.js" in shell.text
    assert shell.headers["content-security-policy"].startswith("default-src 'self'")

    manifest = client.get("/manifest.webmanifest")
    assert manifest.status_code == 200
    assert manifest.json()["start_url"] == "/control/"

    worker = client.get("/sw.js")
    assert worker.status_code == 200
    assert worker.headers["service-worker-allowed"] == "/control/"


def test_control_center_deep_links_resolve_to_spa_shell():
    client = TestClient(create_control_center_app())

    response = client.get("/jobs/J-4831")
    assert response.status_code == 200
    assert "AI Control Center" in response.text


def test_control_center_assets_do_not_expose_parent_paths():
    client = TestClient(create_control_center_app())

    response = client.get("/assets/does-not-exist.js")
    assert response.status_code == 404


def test_control_center_client_uses_only_platform_api_boundary():
    client = TestClient(create_control_center_app())

    javascript = client.get("/assets/app.js")
    assert javascript.status_code == 200
    assert 'const API_BASE = "/control/api/v1"' in javascript.text
    assert "qdrant" not in javascript.text.lower()
    assert "ollama" not in javascript.text.lower()
    assert "postgres" not in javascript.text.lower()


def test_control_center_contains_live_knowledge_workflow_and_registry_client():
    client = TestClient(create_control_center_app())

    javascript = client.get("/assets/app.js").text
    assert 'api("/apps")' in javascript
    assert '"/knowledge/search"' in javascript
    assert '"/knowledge/ask"' in javascript
    assert "/knowledge/documents/" in javascript
    assert "localStorage" not in javascript



def test_control_center_proxy_is_private_network_and_allowlist_only():
    async def run():
        seen = []

        def upstream(request):
            seen.append((request.method, request.url.path, dict(request.headers)))
            return httpx.Response(
                200,
                json={"schema_version": 1, "status": "ready"},
                headers={"x-request-id": "req_proxy"},
            )

        app = create_control_center_app(
            platform_base_url="http://platform/api/v1",
            upstream_transport=httpx.MockTransport(upstream),
        )
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app, client=("192.168.1.40", 1234)),
            base_url="http://control",
        ) as http:
            health = await http.get("/api/v1/health")
            assert health.status_code == 200
            assert health.headers["x-request-id"] == "req_proxy"

            forbidden = await http.post(
                "/api/v1/ai",
                json={"messages": [{"role": "user", "content": "no"}]},
            )
            assert forbidden.status_code == 403
            assert len(seen) == 1

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app, client=("203.0.113.9", 1234)),
            base_url="http://control",
        ) as http:
            assert (await http.get("/api/v1/health")).status_code == 403

    asyncio.run(run())


def test_control_center_proxy_uses_server_side_platform_token_only():
    async def run():
        observed = {}

        def upstream(request):
            observed["authorization"] = request.headers.get("authorization")
            return httpx.Response(200, json={"schema_version": 1, "apps": []})

        from pydantic import SecretStr

        app = create_control_center_app(
            platform_base_url="http://platform/api/v1",
            platform_api_token=SecretStr("server-side-token-value"),
            upstream_transport=httpx.MockTransport(upstream),
        )
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app, client=("100.100.20.30", 1234)),
            base_url="http://control",
        ) as http:
            response = await http.get(
                "/api/v1/apps",
                headers={"authorization": "Bearer browser-supplied-value"},
            )
            assert response.status_code == 200
            assert "server-side-token-value" not in response.text
            assert "browser-supplied-value" not in response.text
        assert observed["authorization"] == "Bearer server-side-token-value"

    asyncio.run(run())
