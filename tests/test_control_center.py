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
    assert 'const API_BASE = "/api/v1"' in javascript.text
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

