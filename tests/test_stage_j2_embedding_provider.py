import pytest

from ai_bridge.ollama.client import OllamaEmbeddingResult
from ai_bridge.providers.contracts import EmbeddingRequest
from ai_bridge.providers.ollama import OllamaEmbeddingAdapter


class FakeEmbeddingClient:
    def __init__(self):
        self.calls = []
        self.available = True

    def embed(self, *, model, inputs, keep_alive):
        self.calls.append({
            "model": model,
            "inputs": inputs,
            "keep_alive": keep_alive,
        })
        return OllamaEmbeddingResult(
            embeddings=tuple((float(index + 1), 0.5, -0.25) for index, _ in enumerate(inputs)),
            model=model,
            prompt_eval_count=7,
            total_duration_ns=2_500_000,
        )

    def is_available(self):
        return self.available


def adapter(client=None):
    return OllamaEmbeddingAdapter(
        client=client or FakeEmbeddingClient(),  # type: ignore[arg-type]
        default_model="embedding-primary-physical",
        query_instruction="Retrieve technical service passages.",
        keep_alive="2m",
    )


def test_query_instruction_is_provider_detail_not_client_contract():
    client = FakeEmbeddingClient()
    provider = adapter(client)
    result = provider.embed(EmbeddingRequest(
        request_id="req-1",
        inputs=("SPN 107 FMI 3",),
        context={"embedding_role": "query"},
    ))

    assert client.calls == [{
        "model": "embedding-primary-physical",
        "inputs": ("Instruct: Retrieve technical service passages.\nQuery: SPN 107 FMI 3",),
        "keep_alive": "2m",
    }]
    assert result.request_id == "req-1"
    assert result.dimensions == 3
    assert result.vectors[0].values == (1.0, 0.5, -0.25)
    assert result.duration_ms == 2.5


def test_document_embedding_does_not_receive_query_instruction():
    client = FakeEmbeddingClient()
    provider = adapter(client)
    provider.embed(EmbeddingRequest(
        request_id="req-doc",
        inputs=("Document body",),
        context={"embedding_role": "document"},
    ))
    assert client.calls[0]["inputs"] == ("Document body",)


def test_embedding_adapter_validates_role_and_dimensions():
    provider = adapter()

    with pytest.raises(ValueError, match="embedding_role"):
        provider.embed(EmbeddingRequest(
            request_id="bad-role",
            inputs=("text",),
            context={"embedding_role": "other"},
        ))

    with pytest.raises(RuntimeError, match="unexpected dimensions"):
        provider.embed(EmbeddingRequest(
            request_id="bad-dims",
            inputs=("text",),
            dimensions_hint=1024,
            context={"embedding_role": "query"},
        ))


def test_embedding_adapter_health_and_descriptor():
    client = FakeEmbeddingClient()
    provider = adapter(client)
    assert provider.health().status == "ready"
    descriptor = provider.describe()
    assert descriptor.provider_id == "embedding-local"
    assert descriptor.provider_type == "embedding"
    assert descriptor.capabilities == ("embeddings",)
    assert descriptor.models == ("embedding-primary-physical",)
    assert descriptor.metadata["query_instruction"] is True

    client.available = False
    assert provider.health().status == "unavailable"
