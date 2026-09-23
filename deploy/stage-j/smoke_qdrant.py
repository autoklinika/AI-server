from __future__ import annotations

import os
import uuid

import httpx

from ai_bridge.knowledge import KnowledgeService
from ai_bridge.knowledge.backends import QdrantKnowledgeBackend
from ai_bridge.providers.contracts import KnowledgeQuery


URL = os.environ.get("QDRANT_URL", "http://127.0.0.1:6333")
COLLECTION = "stage_j_smoke_" + uuid.uuid4().hex[:12]


def main() -> None:
    with httpx.Client(base_url=URL, timeout=10, trust_env=False) as client:
        ready = client.get("/readyz")
        ready.raise_for_status()
        created = client.put(
            f"/collections/{COLLECTION}",
            json={"vectors": {"dense": {"size": 3, "distance": "Cosine"}}},
        )
        created.raise_for_status()
        try:
            upsert = client.put(
                f"/collections/{COLLECTION}/points?wait=true",
                json={"points": [{
                    "id": 1,
                    "vector": {"dense": [1.0, 0.0, 0.0]},
                    "payload": {
                        "text": "MPC564 Stage J live smoke document",
                        "domain": "ecu-repair",
                        "namespace": "ecu-repair",
                        "source_type": "documentation",
                        "source_uri": "repo://stage-j/smoke.md",
                        "source_title": "Stage J smoke",
                        "page": 1,
                    },
                }]},
            )
            upsert.raise_for_status()

            backend = QdrantKnowledgeBackend(url=URL, collection=COLLECTION)
            try:
                result = KnowledgeService(backend).search(KnowledgeQuery(
                    request_id="stage-j-live-smoke",
                    domain="ecu-repair",
                    query="MPC564",
                    mode="semantic",
                    namespaces=("ecu-repair",),
                    source_types=("documentation",),
                    limit=3,
                    query_embedding=(1.0, 0.0, 0.0),
                ))
            finally:
                backend.close()

            assert len(result.results) == 1
            assert result.results[0].source.uri == "repo://stage-j/smoke.md"
            assert result.backend == "knowledge-primary"
            print("PASS: Qdrant live adapter/search/source-attribution")
        finally:
            client.delete(f"/collections/{COLLECTION}").raise_for_status()


if __name__ == "__main__":
    main()
