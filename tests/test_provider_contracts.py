from __future__ import annotations

import inspect
from typing import Any

import pytest

from ai_bridge.analysis import service as analysis_service
from ai_bridge.analysis import service_v12_2 as analysis_service_v12_2
from ai_bridge.ollama.client import OllamaChatResult
from ai_bridge.providers.contracts import LLMProvider, LLMRequest
from ai_bridge.providers.ollama import OllamaAdapter


class FakeOllamaClient:
    def __init__(self, *, available: bool = True) -> None:
        self.available = available
        self.kwargs: dict[str, Any] | None = None

    def is_available(self) -> bool:
        return self.available

    def chat_structured(self, **kwargs) -> OllamaChatResult:
        self.kwargs = kwargs
        return OllamaChatResult(
            content='{"value":"ok"}',
            model="qwen3.6:35b",
            prompt_eval_count=12,
            eval_count=4,
            total_duration_ns=2_500_000,
        )


def _request() -> LLMRequest:
    return LLMRequest(
        request_id="req-stage-c-contract",
        capability="structured-generation",
        messages=[{"role": "user", "content": "test"}],
        response_schema={
            "title": "Response",
            "type": "object",
            "properties": {
                "value": {
                    "title": "Value",
                    "type": "string",
                    "maxLength": 20,
                }
            },
            "required": ["value"],
        },
        temperature=0.0,
        reasoning_enabled=False,
        context={"domain": "wvc"},
    )


def test_ollama_adapter_satisfies_llm_provider_runtime_contract() -> None:
    adapter = OllamaAdapter(
        client=FakeOllamaClient(),  # type: ignore[arg-type]
        default_model="qwen3.6:35b",
        node_id="test-node",
    )
    assert isinstance(adapter, LLMProvider)


def test_ollama_adapter_maps_generic_request_and_response_without_domain_leakage() -> None:
    client = FakeOllamaClient()
    adapter = OllamaAdapter(
        client=client,  # type: ignore[arg-type]
        default_model="qwen3.6:35b",
        node_id="test-node",
    )

    response = adapter.generate(_request())

    assert client.kwargs is not None
    assert client.kwargs["model"] == "qwen3.6:35b"
    assert client.kwargs["think"] is False
    assert client.kwargs["temperature"] == 0.0
    sampling_schema = client.kwargs["response_schema"]
    assert "title" not in sampling_schema
    assert "maxLength" not in sampling_schema["properties"]["value"]

    assert response.request_id == "req-stage-c-contract"
    assert response.content == '{"value":"ok"}'
    assert response.usage.input_tokens == 12
    assert response.usage.output_tokens == 4
    assert response.execution.provider == "ollama-local"
    assert response.execution.model == "qwen3.6:35b"
    assert response.execution.node == "test-node"
    assert response.execution.duration_ns == 2_500_000
    assert response.execution.duration_ms == 2.5


def test_ollama_adapter_health_and_descriptor_contract() -> None:
    ready = OllamaAdapter(
        client=FakeOllamaClient(available=True),  # type: ignore[arg-type]
        default_model="qwen3.6:35b",
        node_id="test-node",
    )
    unavailable = OllamaAdapter(
        client=FakeOllamaClient(available=False),  # type: ignore[arg-type]
        default_model="qwen3.6:35b",
        node_id="test-node",
    )

    assert ready.health().status == "ready"
    assert unavailable.health().status == "unavailable"

    descriptor = ready.describe()
    assert descriptor.provider_id == "ollama-local"
    assert descriptor.provider_type == "llm"
    assert descriptor.node_id == "test-node"
    assert "structured-generation" in descriptor.capabilities
    assert descriptor.models == ("qwen3.6:35b",)
    assert descriptor.metadata["structured_output"] is True
    assert descriptor.metadata["streaming"] is False


def test_ollama_adapter_declares_streaming_boundary_explicitly() -> None:
    adapter = OllamaAdapter(
        client=FakeOllamaClient(),  # type: ignore[arg-type]
        default_model="qwen3.6:35b",
        node_id="test-node",
    )
    with pytest.raises(NotImplementedError):
        next(adapter.stream(_request()))


def test_wvc_analysis_domain_does_not_import_ollama_product_code() -> None:
    for module in (analysis_service, analysis_service_v12_2):
        source = inspect.getsource(module)
        assert "ai_bridge.ollama" not in source
        assert "OllamaClient" not in source
        assert "compact_schema_for_ollama" not in source
