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
    assert 'data-knowledge-tab="history"' in javascript
    assert 'api("/knowledge/history")' in javascript
    assert 'api("/knowledge/history/" + encodeURIComponent(historyId))' in javascript
    assert "function knowledgeHistoryResults()" in javascript
    assert "function loadKnowledgeHistory()" in javascript
    assert "function openKnowledgeHistory(historyId)" in javascript
    assert "/knowledge/documents/" in javascript
    assert "function knowledgeSourceModal()" in javascript
    assert "function openKnowledgeSource(kind, index)" in javascript
    assert 'api("/knowledge/documents/" + encodeURIComponent(target.documentId))' in javascript
    assert 'id="knowledge-source-target"' in javascript
    assert 'scrollIntoView({ block: "center", behavior: "smooth" })' in javascript
    assert "function sourceOriginalPanel(viewer)" in javascript
    assert "function sourceMetadataPanel(viewer)" in javascript
    assert "/provenance" in javascript
    assert "/original" in javascript
    assert "/ers/artifacts/" in javascript
    assert javascript.count('"/content"') == 1
    assert 'target="_blank"' not in javascript
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

def test_control_center_logs_are_read_only_and_rendered():
    async def run():
        seen = []

        def upstream(request):
            seen.append((request.method, request.url.path))
            return httpx.Response(200, json={
                "schema_version": 1,
                "logs": [],
                "retention": {
                    "persistent": False,
                    "limit": 256,
                    "raw_logs_exposed": False,
                    "sources": ["platform-api", "resource-manager"],
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
            assert (await http.get("/api/v1/logs")).status_code == 200
            assert (await http.post("/api/v1/logs")).status_code == 403

        assert seen == [("GET", "/api/v1/logs")]

    asyncio.run(run())

    javascript = TestClient(create_control_center_app()).get("/assets/app.js").text
    assert 'api("/logs")' in javascript
    assert "function logsPage()" in javascript
    assert 'if (path === "/operations/logs") return logsPage();' in javascript
    assert "Log API nie jest jeszcze częścią Platform API v1." not in javascript



def test_control_center_ers_workspace_is_read_only_and_deep_linked():
    async def run():
        seen = []
        case_id = "11111111-1111-4111-8111-111111111111"

        def upstream(request):
            seen.append((request.method, request.url.path))
            if request.url.path.endswith("/" + case_id):
                return httpx.Response(200, json={
                    "schema_version": 1,
                    "case": {"id": case_id, "case_code": "CASE-000001", "title": "Scania EMS S6"},
                    "assets": [], "asset_revisions": [], "ecus": [],
                    "ecu_identity_observations": [], "ecu_software_observations": [],
                    "symptoms": [], "dtcs": [], "measurements": [],
                    "diagnostic_steps": [], "events": [],
                })
            return httpx.Response(200, json={
                "schema_version": 1,
                "cases": [{"id": case_id, "case_code": "CASE-000001", "title": "Scania EMS S6"}],
                "count": 1,
                "limit": 100,
            })

        app = create_control_center_app(
            platform_base_url="http://platform/api/v1",
            upstream_transport=httpx.MockTransport(upstream),
        )
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app, client=("192.168.1.44", 1234)),
            base_url="http://control",
        ) as http:
            assert (await http.get("/api/v1/ers/cases")).status_code == 200
            assert (await http.get(f"/api/v1/ers/cases/{case_id}")).status_code == 200
            assert (await http.post("/api/v1/ers/cases", json={})).status_code == 403
            assert (await http.patch(f"/api/v1/ers/cases/{case_id}", json={})).status_code == 405
            assert (await http.get("/api/v1/ers/cases/not-a-uuid")).status_code == 403
            assert (await http.get("/api/v1/ecu-repair/cases")).status_code == 403

        assert seen == [
            ("GET", "/api/v1/ers/cases"),
            ("GET", f"/api/v1/ers/cases/{case_id}"),
        ]

    asyncio.run(run())

    javascript = TestClient(create_control_center_app()).get("/assets/app.js").text
    assert 'api("/ers/cases")' in javascript
    assert "function ersCasesPage()" in javascript
    assert "function ersCaseDetailPage(caseId)" in javascript
    assert 'controlUrl("/apps/ers/cases/" + encodeURIComponent(item.id))' in javascript
    assert 'api("/ers/cases/" + encodeURIComponent(caseId))' in javascript
    assert 'if (path === "/apps/ers") return ersCasesPage();' in javascript
    assert 'path.startsWith("/apps/ers/cases/")' in javascript
    assert "Domenowa aplikacja ERS jako osobny workspace." not in javascript


def test_control_center_proxy_allows_read_only_knowledge_document_metadata_for_modal():
    async def run():
        seen = []

        def upstream(request):
            seen.append((request.method, request.url.path))
            return httpx.Response(200, json={
                "schema_version": 1,
                "document": {"document_id": "kdoc_test", "title": "Test document", "media_type": "text/markdown"},
                "source": {"title": "Test source", "type": "documentation"},
                "version": {"version_id": "kver_test"},
                "chunks": [{"chunk_id": "kchk_test", "ordinal": 0, "text": "Evidence text", "locator": {"section": "Root cause"}}],
            })

        app = create_control_center_app(
            platform_base_url="http://platform/api/v1",
            upstream_transport=httpx.MockTransport(upstream),
        )
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app, client=("192.168.1.44", 1234)),
            base_url="http://control",
        ) as http:
            response = await http.get("/api/v1/knowledge/documents/kdoc_test")
            assert response.status_code == 200
            assert response.json()["chunks"][0]["chunk_id"] == "kchk_test"
            assert (await http.post("/api/v1/knowledge/documents/kdoc_test", json={})).status_code == 403

        assert seen == [("GET", "/api/v1/knowledge/documents/kdoc_test")]

    asyncio.run(run())


def test_control_center_proxy_allows_read_only_knowledge_history():
    async def run():
        seen = []
        history_id = "kh_0123456789abcdef0123456789abcdef"

        def upstream(request):
            seen.append((request.method, request.url.path))
            if request.url.path.endswith("/" + history_id):
                return httpx.Response(200, json={
                    "schema_version": 1,
                    "item": {
                        "history_id": history_id,
                        "created_at": "2026-09-26T20:00:00+00:00",
                        "query": "Co było przyczyną?",
                        "domain": "ecu-repair",
                        "mode": "hybrid",
                        "response": {
                            "answer": "Uszkodzony przewód.",
                            "claims": [],
                            "insufficient_context": False,
                            "insufficiency_reason": None,
                            "citations": [],
                            "retrieval": {"mode": "hybrid", "backend": "knowledge-primary", "result_count": 1, "duration_ms": 1.0},
                            "execution": {"model": "reasoning-main", "queue_wait_ms": 0.0, "duration_ms": 2.0},
                        },
                    },
                })
            return httpx.Response(200, json={
                "schema_version": 1,
                "history": [],
                "retention": {"persistent": False, "limit": 10, "scope": "platform-runtime"},
            })

        app = create_control_center_app(
            platform_base_url="http://platform/api/v1",
            upstream_transport=httpx.MockTransport(upstream),
        )
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app, client=("192.168.1.44", 1234)),
            base_url="http://control",
        ) as http:
            assert (await http.get("/api/v1/knowledge/history")).status_code == 200
            assert (await http.get(f"/api/v1/knowledge/history/{history_id}")).status_code == 200
            assert (await http.post("/api/v1/knowledge/history", json={})).status_code == 403
            assert (await http.get("/api/v1/knowledge/history/bad/id")).status_code == 403

        assert seen == [
            ("GET", "/api/v1/knowledge/history"),
            ("GET", f"/api/v1/knowledge/history/{history_id}"),
        ]

    asyncio.run(run())


def test_control_center_proxy_embeds_only_allowlisted_original_source_content():
    async def run():
        seen = []
        version_id = "11111111-1111-4111-8111-111111111111"

        def upstream(request):
            seen.append((request.method, request.url.path))
            if request.url.path.endswith("/provenance"):
                return httpx.Response(200, json={
                    "schema_version": 1,
                    "provenance": {
                        "document_id": "kdoc_test",
                        "direct_original": {"media_kind": "pdf"},
                        "related_originals": [],
                    },
                })
            if request.url.path.endswith("/original"):
                return httpx.Response(
                    200,
                    content=b"%PDF-1.7 fake",
                    headers={
                        "content-type": "application/pdf",
                        "content-disposition": "inline; filename*=UTF-8''test.pdf",
                    },
                )
            if request.url.path.endswith("/content"):
                return httpx.Response(
                    200,
                    content=b"\xff\xd8\xffphoto",
                    headers={
                        "content-type": "image/jpeg",
                        "content-disposition": "inline; filename*=UTF-8''photo.jpg",
                    },
                )
            raise AssertionError(request.url.path)

        app = create_control_center_app(
            platform_base_url="http://platform/api/v1",
            upstream_transport=httpx.MockTransport(upstream),
        )
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app, client=("192.168.1.44", 1234)),
            base_url="http://control",
        ) as http:
            provenance = await http.get(
                "/api/v1/knowledge/documents/kdoc_test/provenance"
            )
            assert provenance.status_code == 200
            assert "frame-ancestors 'none'" in provenance.headers["content-security-policy"]

            original = await http.get(
                "/api/v1/knowledge/documents/kdoc_test/original"
            )
            assert original.status_code == 200
            assert original.content.startswith(b"%PDF")
            assert original.headers["content-type"].startswith("application/pdf")
            assert "frame-ancestors 'self'" in original.headers["content-security-policy"]
            assert "script-src 'none'" in original.headers["content-security-policy"]

            photo = await http.get(
                f"/api/v1/ers/artifacts/{version_id}/content"
            )
            assert photo.status_code == 200
            assert photo.content.startswith(b"\xff\xd8\xff")
            assert photo.headers["content-type"].startswith("image/jpeg")
            assert "frame-ancestors 'self'" in photo.headers["content-security-policy"]

            assert (await http.post(
                "/api/v1/knowledge/documents/kdoc_test/original", json={}
            )).status_code == 403
            assert (await http.get(
                "/api/v1/ers/artifacts/not-a-uuid/content"
            )).status_code == 403

        assert seen == [
            ("GET", "/api/v1/knowledge/documents/kdoc_test/provenance"),
            ("GET", "/api/v1/knowledge/documents/kdoc_test/original"),
            ("GET", f"/api/v1/ers/artifacts/{version_id}/content"),
        ]

    asyncio.run(run())
