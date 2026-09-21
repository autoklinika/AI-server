from __future__ import annotations

from dataclasses import fields

import pytest

from ai_bridge.providers.contracts import (
    EmbeddingProvider,
    EmbeddingRequest,
    EmbeddingResult,
    EmbeddingUsage,
    EmbeddingVector,
    KnowledgeBackend,
    KnowledgeQuery,
    KnowledgeResult,
    KnowledgeSearchResult,
    KnowledgeSource,
    ProviderDescriptor,
    ProviderHealth,
)


class FakeEmbeddingProvider:
    def embed(self, request: EmbeddingRequest) -> EmbeddingResult:
        vectors = tuple(
            EmbeddingVector(index=index, values=(float(index), 1.0, 2.0))
            for index, _text in enumerate(request.inputs)
        )
        return EmbeddingResult(
            request_id=request.request_id,
            vectors=vectors,
            provider="embedding-test",
            model=request.model_hint or "embedding-model-test",
            dimensions=3,
            usage=EmbeddingUsage(input_tokens=7),
            duration_ms=1.25,
        )

    def health(self) -> ProviderHealth:
        return ProviderHealth(status="ready")

    def describe(self) -> ProviderDescriptor:
        return ProviderDescriptor(
            provider_id="embedding-test",
            provider_type="embedding",
            node_id="test-node",
            capabilities=("embeddings",),
            models=("embedding-model-test",),
            status="ready",
        )


class FakeKnowledgeBackend:
    def search(self, query: KnowledgeQuery) -> KnowledgeSearchResult:
        return KnowledgeSearchResult(
            request_id=query.request_id,
            results=(
                KnowledgeResult(
                    result_id="kr-1",
                    text="Example result",
                    source=KnowledgeSource(
                        type="documentation",
                        uri="repo://docs/example.md",
                        title="Example",
                    ),
                    score=0.73,
                    metadata={
                        "domain": query.domain,
                        "namespaces": list(query.namespaces),
                        "mode": query.mode,
                    },
                ),
            ),
            backend="knowledge-test",
            duration_ms=2.5,
        )

    def health(self) -> ProviderHealth:
        return ProviderHealth(status="ready")

    def describe(self) -> ProviderDescriptor:
        return ProviderDescriptor(
            provider_id="knowledge-test",
            provider_type="knowledge-backend",
            node_id="test-node",
            capabilities=("exact", "keyword", "semantic", "hybrid"),
            models=(),
            status="ready",
        )


def test_embedding_provider_runtime_contract_and_batch_order() -> None:
    provider = FakeEmbeddingProvider()
    assert isinstance(provider, EmbeddingProvider)

    request = EmbeddingRequest(
        request_id="embed-1",
        inputs=("first", "second"),
        model_hint="logical-embedding-model",
        context={"domain": "ecu-repair"},
    )
    result = provider.embed(request)

    assert result.request_id == "embed-1"
    assert result.provider == "embedding-test"
    assert result.model == "logical-embedding-model"
    assert result.dimensions == 3
    assert [vector.index for vector in result.vectors] == [0, 1]
    assert all(len(vector.values) == result.dimensions for vector in result.vectors)
    assert result.usage.input_tokens == 7


@pytest.mark.parametrize(
    "mode",
    ["exact", "keyword", "semantic", "hybrid", "auto"],
)
def test_knowledge_query_supports_architecture_v1_modes(mode: str) -> None:
    query = KnowledgeQuery(
        request_id=f"knowledge-{mode}",
        domain="ecu-repair",
        query="MPC564",
        mode=mode,  # type: ignore[arg-type]
        namespaces=("ecu-repair", "shared"),
        source_types=("repair-case", "datasheet", "documentation"),
        filters={"manufacturer": "NXP"},
        limit=10,
        query_embedding=(0.1, 0.2, 0.3) if mode in {"semantic", "hybrid"} else None,
    )

    assert query.domain == "ecu-repair"
    assert query.namespaces == ("ecu-repair", "shared")
    assert query.mode == mode


def test_knowledge_backend_runtime_contract_preserves_source_attribution() -> None:
    backend = FakeKnowledgeBackend()
    assert isinstance(backend, KnowledgeBackend)

    query = KnowledgeQuery(
        request_id="knowledge-1",
        domain="ecu-repair",
        query="MPC564",
        mode="hybrid",
        namespaces=("ecu-repair", "shared"),
        source_types=("documentation",),
        query_embedding=(0.1, 0.2, 0.3),
    )
    response = backend.search(query)

    assert response.request_id == query.request_id
    assert response.backend == "knowledge-test"
    assert len(response.results) == 1

    hit = response.results[0]
    assert hit.result_id == "kr-1"
    assert hit.source.type == "documentation"
    assert hit.source.uri == "repo://docs/example.md"
    assert hit.source.title == "Example"
    assert hit.metadata["domain"] == "ecu-repair"
    assert hit.metadata["namespaces"] == ["ecu-repair", "shared"]
    assert hit.metadata["mode"] == "hybrid"


def test_embedding_and_knowledge_contracts_do_not_encode_backend_products() -> None:
    contract_types = (
        EmbeddingRequest,
        EmbeddingResult,
        EmbeddingVector,
        KnowledgeQuery,
        KnowledgeResult,
        KnowledgeSearchResult,
        KnowledgeSource,
    )
    field_names = {
        field.name.casefold()
        for contract_type in contract_types
        for field in fields(contract_type)
    }

    forbidden = {
        "ollama",
        "qwen",
        "qdrant",
        "pgvector",
        "postgres",
        "comfyui",
        "hermes",
    }
    assert field_names.isdisjoint(forbidden)


def test_embedding_and_knowledge_descriptors_use_capabilities_not_backend_urls() -> None:
    embedding = FakeEmbeddingProvider().describe()
    knowledge = FakeKnowledgeBackend().describe()

    assert embedding.capabilities == ("embeddings",)
    assert embedding.node_id == "test-node"
    assert knowledge.capabilities == ("exact", "keyword", "semantic", "hybrid")
    assert knowledge.node_id == "test-node"
