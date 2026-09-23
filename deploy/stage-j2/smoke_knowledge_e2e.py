from __future__ import annotations

import os
import uuid

import httpx

from ai_bridge.knowledge import KnowledgeService
from ai_bridge.knowledge.backends import QdrantKnowledgeBackend
from ai_bridge.providers.contracts import EmbeddingRequest, KnowledgeQuery
from ai_bridge.providers.ollama import OllamaEmbeddingAdapter


GATEWAY_URL = os.environ.get("AI_GATEWAY_URL", "http://127.0.0.1:11435")
QDRANT_URL = os.environ.get("QDRANT_URL", "http://127.0.0.1:6333")
EMBEDDING_MODEL = os.environ.get("KNOWLEDGE_EMBEDDING_MODEL", "bge-m3")
EMBEDDING_DIMENSIONS = int(os.environ.get("KNOWLEDGE_EMBEDDING_DIMENSIONS", "1024"))
QUERY_INSTRUCTION = os.environ.get("KNOWLEDGE_QUERY_INSTRUCTION") or None


def main() -> None:
    collection = "stage_j2_e2e_" + uuid.uuid4().hex[:12]
    embedding = OllamaEmbeddingAdapter.from_endpoint(
        base_url=GATEWAY_URL,
        default_model=EMBEDDING_MODEL,
        timeout_seconds=300,
        request_source="knowledge-e2e-smoke",
        request_priority=100,
        query_instruction=None,
        keep_alive="2m",
    )
    document_text = (
        "CASE-0001 Hatz 3H50TICD. DTC SPN 107 FMI 3. "
        "Bosch air filter differential pressure sensor 0 281 007 439. "
        "The confirmed physical root cause was a damaged electrical wire at the sensor connector."
    )
    document_embedding = embedding.embed(EmbeddingRequest(
        request_id="stage-j2-document",
        inputs=(document_text,),
        dimensions_hint=EMBEDDING_DIMENSIONS,
        context={"embedding_role": "document", "domain": "ecu-repair"},
    ))

    with httpx.Client(base_url=QDRANT_URL, timeout=30, trust_env=False) as client:
        client.put(
            f"/collections/{collection}",
            json={
                "vectors": {
                    "dense": {
                        "size": EMBEDDING_DIMENSIONS,
                        "distance": "Cosine",
                    }
                }
            },
        ).raise_for_status()
        try:
            client.put(
                f"/collections/{collection}/points?wait=true",
                json={
                    "points": [{
                        "id": 1,
                        "vector": {"dense": list(document_embedding.vectors[0].values)},
                        "payload": {
                            "text": document_text,
                            "domain": "ecu-repair",
                            "namespace": "ecu-repair",
                            "source_type": "repair-case",
                            "source_uri": "github://autoklinika/EcuRepairService/CASE-0001",
                            "source_title": "CASE-0001",
                            "page": None,
                        },
                    }]
                },
            ).raise_for_status()

            backend = QdrantKnowledgeBackend(
                url=QDRANT_URL,
                collection=collection,
            )
            try:
                service = KnowledgeService(backend, embedding)
                result = service.search(KnowledgeQuery(
                    request_id="stage-j2-query",
                    domain="ecu-repair",
                    query="Co było przyczyną SPN 107 FMI 3?",
                    mode="semantic",
                    namespaces=("ecu-repair",),
                    source_types=("repair-case",),
                    limit=3,
                ))
            finally:
                backend.close()

            assert len(result.results) == 1
            hit = result.results[0]
            assert "damaged electrical wire" in hit.text
            assert hit.source.uri.endswith("CASE-0001")
            assert result.backend == "knowledge-primary"
            print(
                "PASS: text -> scheduled embedding -> KnowledgeService -> "
                "Qdrant -> attributed result"
            )
        finally:
            client.delete(f"/collections/{collection}").raise_for_status()


if __name__ == "__main__":
    main()
