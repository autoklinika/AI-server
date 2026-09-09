import httpx
from fastapi.testclient import TestClient
from ai_bridge.gateway.app import create_gateway_app
from ai_bridge.settings import Settings

def _upstream(request:httpx.Request)->httpx.Response:
    return httpx.Response(200,json={"choices":[{"message":{"content":"ok"}}]},request=request)

def _app():
    settings=Settings(ollama_url="http://upstream.test",gateway_max_concurrency=1,gateway_max_queue_size=10,gateway_external_lease_ttl_seconds=30)
    return create_gateway_app(settings,upstream_transport=httpx.MockTransport(_upstream))

def test_leased_hermes_request_can_release_slot_on_response():
    with TestClient(_app()) as client:
        lease=client.post("/resource/leases",json={"source":"telegram-chat","priority":50}).json()
        assert lease["state"]=="active"
        response=client.post("/clients/hermes/v1/chat/completions",json={"model":"x","messages":[],"stream":False},headers={"X-AI-Resource-Lease":lease["lease_id"],"X-AI-Resource-Lease-Release":"1"})
        assert response.status_code==200
        assert response.headers["X-AI-Gateway-Job-Id"]==str(lease["job_id"])
        status=client.get("/status").json()
        assert status["active_count"]==0
        assert status["resource_leases"]["lease_count"]==0

def test_media_style_lease_survives_qwen_request_until_explicit_release():
    with TestClient(_app()) as client:
        lease=client.post("/resource/leases",json={"source":"telegram-wideo","priority":50}).json()
        response=client.post("/clients/hermes/v1/chat/completions",json={"model":"x","messages":[],"stream":False},headers={"X-AI-Resource-Lease":lease["lease_id"]})
        assert response.status_code==200
        status=client.get("/status").json()
        assert status["active_count"]==1
        assert status["resource_leases"]["lease_count"]==1
        assert client.delete(f"/resource/leases/{lease['lease_id']}").json()["released"] is True
        assert client.get("/status").json()["active_count"]==0
