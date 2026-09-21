from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
import pytest

from ai_bridge.providers.comfyui import (
    ComfyUIAdapter,
    ComfyUIWorkflowPlan,
    MediaProviderError,
)
from ai_bridge.providers.contracts import (
    MediaGenerationProvider,
    MediaGenerationRequest,
)


def _request(tmp_path: Path) -> MediaGenerationRequest:
    return MediaGenerationRequest(
        request_id="req-media-stage-c",
        capability="video-generation",
        profile="ltx23-stage30",
        prompt="red robot waves",
        output_dir=str(tmp_path),
        timeout_seconds=30.0,
        parameters={"width": 640, "height": 384},
        context={"domain": "shared"},
    )


def _resolver(
    request: MediaGenerationRequest,
    staged_inputs: tuple[str, ...],
) -> ComfyUIWorkflowPlan:
    assert request.profile == "ltx23-stage30"
    assert len(staged_inputs) <= 1
    return ComfyUIWorkflowPlan(
        graph={
            "1": {
                "class_type": "SaveVideo",
                "inputs": {"filename_prefix": "hermes-video/LTX23"},
            }
        },
        output_extensions=(".mp4", ".webm"),
        filename_tag="ltx23",
        media_type="video/mp4",
        metadata={"workflow": "ltx23-stage30"},
    )


def _adapter(*, input_dir: str | None = None) -> ComfyUIAdapter:
    return ComfyUIAdapter(
        base_url="http://127.0.0.1:8188",
        workflow_resolver=_resolver,
        profiles=("ltx23-stage30",),
        capabilities=("video-generation",),
        node_id="test-node",
        poll_seconds=0.0,
        input_dir=input_dir,
    )


def test_comfyui_adapter_satisfies_media_provider_runtime_contract() -> None:
    assert isinstance(_adapter(), MediaGenerationProvider)


def test_media_contract_does_not_expose_comfyui_product_fields() -> None:
    fields = set(MediaGenerationRequest.__dataclass_fields__)
    assert "comfy_url" not in fields
    assert "graph" not in fields
    assert "prompt_id" not in fields
    assert "node_id" not in fields


def test_comfyui_adapter_maps_logical_request_to_backend_and_artifact(
    monkeypatch,
    tmp_path,
) -> None:
    calls: list[tuple[str, str, Any]] = []

    def fake_request(
        method: str,
        url: str,
        *,
        json: dict | None,
        timeout: float,
    ) -> httpx.Response:
        calls.append((method, url, json))
        req = httpx.Request(method, url)
        if url.endswith("/prompt"):
            return httpx.Response(200, json={"prompt_id": "prompt-abc"}, request=req)
        if url.endswith("/history/prompt-abc"):
            return httpx.Response(
                200,
                json={
                    "prompt-abc": {
                        "outputs": {
                            "20": {
                                "videos": [
                                    {
                                        "filename": "LTX23_001.mp4",
                                        "subfolder": "hermes-video",
                                        "type": "output",
                                    }
                                ]
                            }
                        },
                        "status": {"status_str": "success", "completed": True},
                    }
                },
                request=req,
            )
        if url.endswith("/free"):
            return httpx.Response(200, json={}, request=req)
        raise AssertionError(f"unexpected request: {method} {url}")

    def fake_get(url: str, *, timeout: float) -> httpx.Response:
        calls.append(("GET_BYTES", url, None))
        return httpx.Response(
            200,
            content=b"fake-mp4-bytes",
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr(httpx, "request", fake_request)
    monkeypatch.setattr(httpx, "get", fake_get)

    result = _adapter().generate(_request(tmp_path))

    assert result.request_id == "req-media-stage-c"
    assert result.capability == "video-generation"
    assert result.profile == "ltx23-stage30"
    assert result.provider == "comfyui-local"
    assert result.provider_metadata["prompt_id"] == "prompt-abc"
    assert result.provider_metadata["workflow"] == "ltx23-stage30"

    assert len(result.artifacts) == 1
    artifact = result.artifacts[0]
    target = Path(artifact.uri)
    assert target.exists()
    assert target.read_bytes() == b"fake-mp4-bytes"
    assert artifact.media_type == "video/mp4"
    assert artifact.size_bytes == len(b"fake-mp4-bytes")
    assert artifact.metadata["source_filename"] == "LTX23_001.mp4"

    prompt_call = next(call for call in calls if call[1].endswith("/prompt"))
    assert prompt_call[0] == "POST"
    assert prompt_call[2]["prompt"] == _resolver(_request(tmp_path), ()).graph
    assert isinstance(prompt_call[2]["client_id"], str)
    assert prompt_call[2]["client_id"]

    history_call = next(
        call for call in calls if call[1].endswith("/history/prompt-abc")
    )
    assert history_call[0] == "GET"

    download_call = next(call for call in calls if call[0] == "GET_BYTES")
    assert download_call[1].startswith("http://127.0.0.1:8188/view?")
    assert "filename=LTX23_001.mp4" in download_call[1]
    assert "subfolder=hermes-video" in download_call[1]

    free_call = next(call for call in calls if call[1].endswith("/free"))
    assert free_call[0] == "POST"
    assert free_call[2] == {"unload_models": True, "free_memory": True}





def test_comfyui_adapter_stages_and_cleans_input_artifact(
    monkeypatch,
    tmp_path,
) -> None:
    source = tmp_path / "input.png"
    source.write_bytes(b"png-bytes")
    provider_input = tmp_path / "provider-input"
    output_dir = tmp_path / "out"

    captured_staged: list[str] = []

    def resolver(
        request: MediaGenerationRequest,
        staged_inputs: tuple[str, ...],
    ) -> ComfyUIWorkflowPlan:
        assert request.input_artifacts == (str(source),)
        assert len(staged_inputs) == 1
        captured_staged.extend(staged_inputs)
        staged = provider_input / staged_inputs[0]
        assert staged.exists()
        assert staged.read_bytes() == b"png-bytes"
        return ComfyUIWorkflowPlan(
            graph={
                "1": {
                    "class_type": "LoadImage",
                    "inputs": {"image": staged_inputs[0]},
                },
                "2": {
                    "class_type": "SaveVideo",
                    "inputs": {"filename_prefix": "hermes-video/LTX23"},
                },
            },
            output_extensions=(".mp4",),
            filename_tag="ltx23",
            media_type="video/mp4",
        )

    def fake_request(
        method: str,
        url: str,
        *,
        json: dict | None,
        timeout: float,
    ) -> httpx.Response:
        req = httpx.Request(method, url)
        if url.endswith("/prompt"):
            assert json is not None
            assert json["prompt"]["1"]["inputs"]["image"] == captured_staged[0]
            return httpx.Response(200, json={"prompt_id": "prompt-i2v"}, request=req)
        if url.endswith("/history/prompt-i2v"):
            return httpx.Response(
                200,
                json={
                    "prompt-i2v": {
                        "outputs": {
                            "2": {
                                "videos": [
                                    {
                                        "filename": "i2v.mp4",
                                        "subfolder": "",
                                        "type": "output",
                                    }
                                ]
                            }
                        }
                    }
                },
                request=req,
            )
        if url.endswith("/free"):
            return httpx.Response(200, json={}, request=req)
        raise AssertionError(url)

    monkeypatch.setattr(httpx, "request", fake_request)
    monkeypatch.setattr(
        httpx,
        "get",
        lambda url, *, timeout: httpx.Response(
            200,
            content=b"video",
            request=httpx.Request("GET", url),
        ),
    )

    adapter = ComfyUIAdapter(
        base_url="http://127.0.0.1:8188",
        workflow_resolver=resolver,
        profiles=("ltx23-stage30",),
        capabilities=("video-generation",),
        poll_seconds=0.0,
        input_dir=str(provider_input),
    )
    request = MediaGenerationRequest(
        request_id="req-i2v",
        capability="video-generation",
        profile="ltx23-stage30",
        prompt="animate",
        output_dir=str(output_dir),
        input_artifacts=(str(source),),
    )

    result = adapter.generate(request)

    assert len(result.artifacts) == 1
    assert captured_staged
    assert not (provider_input / captured_staged[0]).exists()


def test_comfyui_adapter_normalizes_execution_error(monkeypatch, tmp_path) -> None:
    def fake_request(
        method: str,
        url: str,
        *,
        json: dict | None,
        timeout: float,
    ) -> httpx.Response:
        req = httpx.Request(method, url)
        if url.endswith("/prompt"):
            return httpx.Response(200, json={"prompt_id": "prompt-error"}, request=req)
        if url.endswith("/history/prompt-error"):
            return httpx.Response(
                200,
                json={
                    "prompt-error": {
                        "status": {
                            "messages": [
                                [
                                    "execution_error",
                                    {"node_id": "20", "exception_message": "OOM"},
                                ]
                            ]
                        }
                    }
                },
                request=req,
            )
        raise AssertionError(url)

    monkeypatch.setattr(httpx, "request", fake_request)

    with pytest.raises(MediaProviderError, match="Media generation failed"):
        _adapter().generate(_request(tmp_path))


def test_comfyui_adapter_health_and_descriptor(monkeypatch) -> None:
    def fake_request(
        method: str,
        url: str,
        *,
        json: dict | None,
        timeout: float,
    ) -> httpx.Response:
        assert method == "GET"
        assert url == "http://127.0.0.1:8188/system_stats"
        return httpx.Response(
            200,
            json={"system": {"os": "linux"}},
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr(httpx, "request", fake_request)
    adapter = _adapter()

    assert adapter.health().status == "ready"
    descriptor = adapter.describe()
    assert descriptor.provider_id == "comfyui-local"
    assert descriptor.provider_type == "media-generation"
    assert descriptor.node_id == "test-node"
    assert descriptor.capabilities == ("video-generation",)
    assert descriptor.models == ("ltx23-stage30",)
    assert descriptor.metadata["transport"] == "http"
    assert descriptor.metadata["artifact_delivery"] == "download"


def test_comfyui_adapter_health_reports_unavailable(monkeypatch) -> None:
    def failing_request(*_args, **_kwargs):
        raise httpx.ConnectError("offline")

    monkeypatch.setattr(httpx, "request", failing_request)
    health = _adapter().health()

    assert health.status == "unavailable"
    assert "Media backend unavailable" in (health.detail or "")


def test_comfyui_adapter_rejects_unknown_profile_before_backend_call(tmp_path) -> None:
    adapter = _adapter()
    request = MediaGenerationRequest(
        request_id="req-media-stage-c",
        capability="video-generation",
        profile="unknown",
        prompt="test",
        output_dir=str(tmp_path),
    )

    with pytest.raises(ValueError, match="Unsupported media profile"):
        adapter.generate(request)
