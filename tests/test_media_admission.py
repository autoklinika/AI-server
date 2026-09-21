from contextlib import contextmanager
import importlib.util
from pathlib import Path
import sys

import httpx
import pytest

from ai_bridge.providers.comfyui import ComfyUIAdapter, MediaProviderError
from ai_bridge.providers.contracts import MediaGenerationRequest
from ai_bridge.providers.media_admission import MediaAdmissionError, media_admission


@pytest.mark.parametrize("lease,gateway", [("", "http://127.0.0.1:11435"), ("../secret", "http://127.0.0.1:11435"), ("lease", "http://127.0.0.1:11434"), ("lease", "http://example.com:11435"), ("lease", "http://127.0.0.1:bad")])
def test_media_guard_fails_closed_before_network(monkeypatch, lease, gateway):
    monkeypatch.setenv("HERMES_RESOURCE_LEASE_ID", lease)
    monkeypatch.setenv("HERMES_RESOURCE_GATEWAY_URL", gateway)
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: pytest.fail("no network allowed"))
    with pytest.raises(MediaAdmissionError):
        with media_admission("video-generation"):
            pytest.fail("unadmitted execution")


@pytest.mark.parametrize("status", [404, 409, 500])
def test_media_guard_denial_does_not_execute_or_echo_response(monkeypatch, status):
    monkeypatch.setenv("HERMES_RESOURCE_LEASE_ID", "lease")
    monkeypatch.delenv("HERMES_RESOURCE_GATEWAY_URL", raising=False)
    client_type = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: client_type(**kwargs, transport=httpx.MockTransport(lambda request: httpx.Response(status, text="private content"))))
    with pytest.raises(MediaAdmissionError, match="^media admission unavailable$"):
        with media_admission("video-generation"):
            pytest.fail("unadmitted execution")


@pytest.mark.parametrize("failure", [False, True])
def test_media_guard_claims_and_releases_phase_on_success_and_error(monkeypatch, failure):
    monkeypatch.setenv("HERMES_RESOURCE_LEASE_ID", "lease")
    monkeypatch.delenv("HERMES_RESOURCE_GATEWAY_URL", raising=False)
    calls = []
    def upstream(request):
        calls.append(request)
        return httpx.Response(201, json={"use_id": "use-1"})
    client_type = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: client_type(**kwargs, transport=httpx.MockTransport(upstream)))
    try:
        with media_admission("video-generation"):
            assert len(calls) == 1
            if failure:
                raise RuntimeError("executor failure")
    except RuntimeError:
        assert failure
    assert [request.method for request in calls] == ["POST", "DELETE"]
    assert calls[1].url.path == "/resource/leases/lease/uses/use-1"
    assert calls[0].content == b'{"provider":"comfyui-local","capability":"video-generation"}'


def test_comfyui_adapter_requires_admission_before_resolver_or_files(monkeypatch, tmp_path):
    monkeypatch.delenv("HERMES_RESOURCE_LEASE_ID", raising=False)
    adapter = ComfyUIAdapter(base_url="http://127.0.0.1:8188", profiles=("test",), workflow_resolver=lambda *args: pytest.fail("must not prepare workflow"))
    request = MediaGenerationRequest(request_id="req", capability="video-generation", profile="test", prompt="private", output_dir=str(tmp_path))
    with pytest.raises(MediaProviderError, match="active local resource lease required"):
        adapter.generate(request)
    assert not list(tmp_path.iterdir())


def test_adapter_guard_spans_backend_execution(monkeypatch, tmp_path):
    events = []
    @contextmanager
    def admission(capability):
        events.append("admit")
        try:
            yield
        finally:
            events.append("release")
    def execute(self, request):
        events.append("execute")
        raise RuntimeError("execution failure")
    monkeypatch.setattr("ai_bridge.providers.comfyui.media_admission", admission)
    monkeypatch.setattr(ComfyUIAdapter, "_generate_admitted", execute)
    adapter = ComfyUIAdapter(base_url="http://127.0.0.1:8188", profiles=("test",), workflow_resolver=lambda *args: None)
    with pytest.raises(RuntimeError):
        adapter.generate(MediaGenerationRequest(request_id="req", capability="video-generation", profile="test", prompt="private", output_dir=str(tmp_path)))
    assert events == ["admit", "execute", "release"]


def test_legacy_image_wrapper_claims_only_generator_phase(monkeypatch):
    path = Path(__file__).resolve().parents[1] / "tools/local_image/hermes_foto_dispatch_global.py"
    spec = importlib.util.spec_from_file_location("d4_image_wrapper", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    events = []
    @contextmanager
    def admission(capability):
        events.append(capability)
        try:
            yield
        finally:
            events.append("released")
    monkeypatch.setattr(module.resource, "media_admission", admission)
    monkeypatch.setattr(module, "_original_generator", lambda request, log: events.append("execute"))
    module.base._run_generator({"input_image": "image.png"}, None)
    assert events == ["image-edit", "execute", "released"]


def test_legacy_media_client_workload_and_cleanup(monkeypatch):
    from test_hermes_resource_queue import mod
    calls = []
    def fake_json(method, path, payload=None, timeout=5):
        calls.append((method, path, payload))
        return {"lease_id": "lease", "job_id": 1, "state": "active", "use_id": "use"}
    monkeypatch.setattr(mod, "_json", fake_json)
    monkeypatch.setattr(mod.ResourceLease, "start_heartbeat", lambda self: None)
    lease = mod.acquire_resource(target=None, source="media", workload="media-video")
    assert calls[0][2]["workload"] == "media-video"
    monkeypatch.setenv("HERMES_RESOURCE_LEASE_ID", lease.lease_id)
    with pytest.raises(RuntimeError):
        with mod.media_admission("video-generation"):
            raise RuntimeError("failed")
    assert calls[-1][:2] == ("DELETE", "/resource/leases/lease/uses/use")
    lease.release()
