import json

import httpx
import pytest

from ai_bridge.knowledge import KnowledgeContractError, KnowledgeService
from ai_bridge.knowledge.backends import QdrantKnowledgeBackend
from ai_bridge.providers.contracts import (
    EmbeddingResult,
    EmbeddingVector,
    KnowledgeQuery,
    KnowledgeResult,
    KnowledgeSearchResult,
    KnowledgeSource,
    ProviderDescriptor,
    ProviderHealth,
)


def query(**overrides):
    values = dict(
        request_id="req-knowledge-1", domain="ecu-repair", query="MPC564 temperature",
        mode="semantic", namespaces=("ecu-repair", "shared"),
        source_types=("datasheet",), filters={"manufacturer": "NXP"}, limit=5,
        query_embedding=(0.1, 0.2, 0.3),
    )
    values.update(overrides)
    return KnowledgeQuery(**values)

def test_qdrant_adapter_translates_neutral_contract_and_preserves_sources():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/readyz":
            return httpx.Response(200, text="ok")
        seen["path"] = request.url.path
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"result": {"points": [{
            "id": "chunk-1", "score": 0.93,
            "payload": {"text": "Maximum junction temperature...", "domain": "ecu-repair",
                        "namespace": "ecu-repair", "manufacturer": "NXP",
                        "source_type": "datasheet", "source_uri": "repo://ecu/mpc564.pdf",
                        "source_title": "MPC564 datasheet", "page": 42},
        }]}})

    backend = QdrantKnowledgeBackend(
        url="http://qdrant.invalid", collection="knowledge-v1",
        transport=httpx.MockTransport(handler),
    )
    result = KnowledgeService(backend).search(query())

    assert seen["path"] == "/collections/knowledge-v1/points/query"
    assert seen["body"]["using"] == "dense"
    assert seen["body"]["query"] == [0.1, 0.2, 0.3]
    assert seen["body"]["limit"] == 5
    assert {item["key"] for item in seen["body"]["filter"]["must"]} == {
        "domain", "namespace", "source_type", "manufacturer"
    }
    assert result.backend == "knowledge-primary"
    assert result.backend_metadata == {"contract_version": 1}
    assert result.results[0].source.uri == "repo://ecu/mpc564.pdf"
    assert result.results[0].source.title == "MPC564 datasheet"
    assert result.results[0].metadata["page"] == 42
    assert "qdrant" not in repr(result).lower()
    assert backend.health().status == "ready"
    backend.close()


def test_service_can_create_embedding_without_exposing_it_to_client():
    class FakeEmbeddingProvider:
        def embed(self, request):
            assert request.inputs == ("MPC564 temperature",)
            assert request.context["embedding_role"] == "query"
            assert request.context["domain"] == "ecu-repair"
            return EmbeddingResult(
                request_id=request.request_id,
                vectors=(EmbeddingVector(index=0, values=(0.1, 0.2, 0.3)),),
                provider="embedding-local", model="test", dimensions=3,
            )

    backend = AlternateBackend()
    result = KnowledgeService(backend, FakeEmbeddingProvider()).search(
        query(query_embedding=None)
    )
    assert result.results[0].text == "alternate result"


def test_qdrant_adapter_rejects_capabilities_not_implemented_in_j1():
    backend = QdrantKnowledgeBackend(
        url="http://qdrant.invalid", collection="knowledge-v1",
        transport=httpx.MockTransport(lambda request: httpx.Response(200)),
    )
    with pytest.raises(ValueError, match="capability unavailable"):
        backend.search(query(mode="keyword", query_embedding=None))
    backend.close()

class AlternateBackend:
    def search(self, request):
        return KnowledgeSearchResult(
            request_id=request.request_id, backend="knowledge-primary",
            results=(KnowledgeResult(
                result_id="alt-1", text="alternate result", score=1.0,
                source=KnowledgeSource(type="documentation", uri="repo://alt.md"),
            ),),
        )

    def health(self):
        return ProviderHealth(status="ready")

    def describe(self):
        return ProviderDescriptor(
            provider_id="knowledge-primary", provider_type="knowledge-backend", node_id=None,
            capabilities=("semantic-search",), models=(), status="ready",
        )


def test_backend_can_be_replaced_without_changing_knowledge_service_client():
    result = KnowledgeService(AlternateBackend()).search(query())
    assert result.backend == "knowledge-primary"
    assert result.results[0].text == "alternate result"

def test_service_fails_closed_when_backend_loses_source_attribution():
    class Broken(AlternateBackend):
        def search(self, request):
            return KnowledgeSearchResult(
                request_id=request.request_id, backend="knowledge-primary",
                results=(KnowledgeResult(
                    result_id="broken", text="text", score=1.0,
                    source=KnowledgeSource(type="documentation", uri=""),
                ),),
            )

    with pytest.raises(KnowledgeContractError, match="source attribution"):
        KnowledgeService(Broken()).search(query())
