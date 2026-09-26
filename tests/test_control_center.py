import asyncio

import httpx
from fastapi.testclient import TestClient

from ai_bridge.control_center.app import create_control_center_app


def test_control_center_serves_shell_and_pwa_assets():
    client = TestClient(create_control_center_app())

    shell = client.get("/")
    assert shell.status_code == 200
    assert shell.headers["cache-control"] == "no-cache, must-revalidate"
    assert "AI Control Center" in shell.text
    assert "/control/assets/app.js" in shell.text
    assert shell.headers["content-security-policy"].startswith("default-src 'self'")

    manifest = client.get("/manifest.webmanifest")
    assert manifest.status_code == 200
    assert manifest.json()["start_url"] == "/control/"

    worker = client.get("/sw.js")
    assert worker.status_code == 200
    assert worker.headers["service-worker-allowed"] == "/control/"
    assert 'ai-control-shell-v2' in worker.text
    assert 'fetch(request, { cache: "no-cache" })' in worker.text


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
            operations = await http.get("/api/v1/operations")
            assert operations.status_code == 200
            traces = await http.get("/api/v1/traces")
            assert traces.status_code == 200

            forbidden = await http.post(
                "/api/v1/ai",
                json={"messages": [{"role": "user", "content": "no"}]},
            )
            assert forbidden.status_code == 403
            assert len(seen) == 3

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


def test_control_center_proxy_allows_read_only_benchmark_catalog():
    async def run():
        seen = []

        def upstream(request):
            seen.append((request.method, request.url.path))
            return httpx.Response(200, json={"schema_version": 1, "suites": []})

        app = create_control_center_app(
            platform_base_url="http://platform/api/v1",
            upstream_transport=httpx.MockTransport(upstream),
        )
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app, client=("192.168.1.44", 1234)),
            base_url="http://control",
        ) as http:
            assert (await http.get("/api/v1/benchmarks")).status_code == 200
            assert (await http.get("/api/v1/benchmarks/knowledge-retrieval/runs")).status_code == 200
            assert (await http.post("/api/v1/benchmarks/knowledge-retrieval/runs")).status_code == 403
        assert seen == [
            ("GET", "/api/v1/benchmarks"),
            ("GET", "/api/v1/benchmarks/knowledge-retrieval/runs"),
        ]
    asyncio.run(run())


def test_control_center_benchmark_ui_has_run_deep_links_and_metrics():
    client = TestClient(create_control_center_app())
    javascript = client.get("/assets/app.js").text

    assert "benchmarkRunPage" in javascript
    assert "loadBenchmarkRun" in javascript
    assert "'/runs/' + encodeURIComponent(run.run_id)" in javascript
    assert "recall_at_1" in javascript
    assert "recall_at_3" in javascript
    assert "recall_at_5" in javascript
    assert "metrics.mrr" in javascript
    assert "latency.search_avg" in javascript
    assert "latency.query_embedding_total" in javascript



def test_control_center_operations_ui_is_live_not_placeholder():
    client = TestClient(create_control_center_app())
    javascript = client.get("/assets/app.js").text
    assert 'api("/operations")' in javascript
    assert "function backupPage()" in javascript
    assert 'metric("Storage", storageValue' in javascript
    assert "Status backupu nie ma jeszcze stabilnego kontraktu" not in javascript

def test_control_center_flight_recorder_ui_has_deep_links_and_no_payload_rendering():
    client = TestClient(create_control_center_app())
    javascript = client.get("/assets/app.js").text

    assert 'api("/traces")' in javascript
    assert "function flightRecorderPage()" in javascript
    assert "function traceDetailPage(traceId)" in javascript
    assert 'controlUrl("/traces/" + encodeURIComponent(trace.trace_id))' in javascript
    recorder = javascript[javascript.index("function flightRecorderPage()"):javascript.index("function traceDetailPage(traceId)")]
    assert "messages" not in recorder
    assert "content" not in recorder

def test_control_center_system_map_is_read_only_and_rendered():
    async def run():
        seen = []
        def upstream(request):
            seen.append((request.method, request.url.path))
            return httpx.Response(200, json={
                "schema_version": 1, "nodes": [], "edges": [], "activity": {},
                "retention": {"persistent": False, "trace_sample_limit": 64},
            })
        app = create_control_center_app(
            platform_base_url="http://platform/api/v1",
            upstream_transport=httpx.MockTransport(upstream),
        )
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app, client=("192.168.1.44", 1234)),
            base_url="http://control",
        ) as http:
            assert (await http.get("/api/v1/system-map")).status_code == 200
            assert (await http.post("/api/v1/system-map")).status_code == 403
        assert seen == [("GET", "/api/v1/system-map")]

    asyncio.run(run())

    javascript = TestClient(create_control_center_app()).get("/assets/app.js").text
    assert 'api("/system-map")' in javascript
    assert "function systemMapPage()" in javascript
    assert '"/apps/system-map"' in javascript



def test_control_center_assets_revalidate_and_service_worker_does_not_pin_old_gui():
    client = TestClient(create_control_center_app())

    asset = client.get("/assets/app.js")
    assert asset.status_code == 200
    assert asset.headers["cache-control"] == "no-cache, must-revalidate"
    assert 'updateViaCache: "none"' in asset.text

    worker = client.get("/sw.js").text
    assert "caches.match(request).then" in worker
    assert "fetch(request, { cache: \"no-cache\" })" in worker
    assert 'ai-control-gui0-v1' not in worker

def test_control_center_incident_timeline_is_read_only_and_deep_linked():
    async def run():
        seen = []

        def upstream(request):
            seen.append((request.method, request.url.path))
            return httpx.Response(200, json={
                "schema_version": 1,
                "incidents": [],
                "retention": {"persistent": False, "source": "flight-recorder", "trace_limit": 256},
            })

        app = create_control_center_app(
            platform_base_url="http://platform/api/v1",
            upstream_transport=httpx.MockTransport(upstream),
        )
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app, client=("192.168.1.44", 1234)),
            base_url="http://control",
        ) as http:
            assert (await http.get("/api/v1/incidents")).status_code == 200
            assert (await http.get("/api/v1/incidents/req_test")).status_code == 200
            assert (await http.post("/api/v1/incidents")).status_code == 403

        assert seen == [
            ("GET", "/api/v1/incidents"),
            ("GET", "/api/v1/incidents/req_test"),
        ]

    asyncio.run(run())

    javascript = TestClient(create_control_center_app()).get("/assets/app.js").text
    assert 'api("/incidents")' in javascript
    assert "function incidentTimelinePage()" in javascript
    assert "function incidentDetailPage(incidentId)" in javascript
    assert 'controlUrl("/incidents/" + encodeURIComponent(incident.incident_id))' in javascript
    assert "function loadIncidentDetail(incidentId)" in javascript
    assert "api('/incidents/' + encodeURIComponent(incidentId))" in javascript

def test_control_center_agents_ui_is_live_and_registry_keeps_operations():
    client = TestClient(create_control_center_app())
    javascript = client.get("/assets/app.js").text

    assert 'api("/agents")' in javascript
    assert "function agentsPage()" in javascript
    assert 'if (path === "/operations/agents") return agentsPage();' in javascript
    assert "Agent control API nie jest jeszcze wystawione" not in javascript
    assert "FALLBACK_APP_REGISTRY.map" in javascript
    assert 'group: "applications"' in javascript


def test_control_center_proxy_allows_read_only_agents():
    async def run():
        seen = []

        def upstream(request):
            seen.append((request.method, request.url.path))
            return httpx.Response(200, json={
                "schema_version": 1,
                "agents": [],
                "retention": {
                    "persistent": True,
                    "source": "bounded-status-files",
                    "raw_logs_exposed": False,
                },
            })

        app = create_control_center_app(
            platform_base_url="http://platform/api/v1",
            upstream_transport=httpx.MockTransport(upstream),
        )
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app, client=("192.168.1.44", 1234)),
            base_url="http://control",
        ) as http:
            assert (await http.get("/api/v1/agents")).status_code == 200
            assert (await http.post("/api/v1/agents")).status_code == 403

        assert seen == [("GET", "/api/v1/agents")]

    asyncio.run(run())

