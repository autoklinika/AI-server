from __future__ import annotations

from dataclasses import dataclass
import uuid

import httpx

from ai_bridge.knowledge.storage.repository import KnowledgeRepository
from ai_bridge.providers.contracts import EmbeddingProvider, EmbeddingRequest


@dataclass(frozen=True)
class DenseIndexProfile:
    profile_id: str
    collection: str
    dimensions: int = 1024
    vector_name: str = "dense"
    distance: str = "Cosine"
    batch_size: int = 32

    def __post_init__(self) -> None:
        if not self.profile_id.strip() or not self.collection.strip():
            raise ValueError("profile_id and collection are required")
        if self.dimensions < 1:
            raise ValueError("dimensions must be positive")
        if not 1 <= self.batch_size <= 256:
            raise ValueError("batch_size must be between 1 and 256")


class QdrantKnowledgeProjector:
    """Project canonical current document chunks into a disposable Qdrant index."""

    def __init__(
        self,
        *,
        repository: KnowledgeRepository,
        embedding_provider: EmbeddingProvider,
        qdrant_url: str,
        profile: DenseIndexProfile,
        timeout_seconds: float = 30.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.repository = repository
        self.embedding_provider = embedding_provider
        self.profile = profile
        self._client = httpx.Client(
            base_url=qdrant_url.rstrip("/"),
            timeout=timeout_seconds,
            transport=transport,
            trust_env=False,
        )

    def close(self) -> None:
        self._client.close()

    def ensure_collection(self) -> None:
        response = self._client.get(f"/collections/{self.profile.collection}")
        if response.status_code == 404:
            created = self._client.put(
                f"/collections/{self.profile.collection}",
                json={
                    "vectors": {
                        self.profile.vector_name: {
                            "size": self.profile.dimensions,
                            "distance": self.profile.distance,
                        }
                    }
                },
            )
            created.raise_for_status()
            self._ensure_payload_indexes()
            return
        response.raise_for_status()
        data = response.json()
        config = ((data.get("result") or {}).get("config") or {}).get("params") or {}
        vectors = config.get("vectors") or {}
        dense = vectors.get(self.profile.vector_name) or {}
        if dense.get("size") != self.profile.dimensions:
            raise RuntimeError("Qdrant collection has unexpected vector dimensions")
        distance = str(dense.get("distance", "")).casefold()
        if distance != self.profile.distance.casefold():
            raise RuntimeError("Qdrant collection has unexpected distance metric")
        self._ensure_payload_indexes()

    def _ensure_payload_indexes(self) -> None:
        for field_name in (
            "domain",
            "namespace",
            "source_type",
            "source_id",
            "document_id",
            "version_id",
            "chunk_profile",
        ):
            response = self._client.put(
                f"/collections/{self.profile.collection}/index",
                params={"wait": "true"},
                json={"field_name": field_name, "field_schema": "keyword"},
            )
            response.raise_for_status()

    def project(self, job_id: str) -> bool:
        if not self.repository.mark_index_running(job_id):
            return False
        work = self.repository.get_index_work(job_id)
        if work.index_profile != self.profile.profile_id:
            self.repository.mark_index_failed(
                job_id, "index job/profile mismatch"
            )
            raise ValueError("index job/profile mismatch")
        try:
            self.ensure_collection()
            vectors: list[tuple[float, ...]] = []
            for start in range(0, len(work.chunks), self.profile.batch_size):
                batch = work.chunks[start:start + self.profile.batch_size]
                result = self.embedding_provider.embed(EmbeddingRequest(
                    request_id=f"{job_id}:embed:{start}",
                    inputs=tuple(chunk.text for chunk in batch),
                    dimensions_hint=self.profile.dimensions,
                    context={
                        "embedding_role": "document",
                        "domain": work.source.domain,
                        "knowledge_index_job_id": job_id,
                    },
                ))
                if len(result.vectors) != len(batch):
                    raise RuntimeError("embedding provider returned wrong vector count")
                ordered = sorted(result.vectors, key=lambda item: item.index)
                if [item.index for item in ordered] != list(range(len(batch))):
                    raise RuntimeError("embedding provider returned invalid vector indexes")
                vectors.extend(item.values for item in ordered)

            self._delete_document(work.document_id)
            self._upsert(work, vectors)
            self.repository.mark_index_completed(job_id)
            return True
        except Exception as exc:
            self.repository.mark_index_failed(job_id, f"{type(exc).__name__}: {exc}")
            raise

    def _delete_document(self, document_id: str) -> None:
        response = self._client.post(
            f"/collections/{self.profile.collection}/points/delete",
            params={"wait": "true"},
            json={
                "filter": {
                    "must": [{
                        "key": "document_id",
                        "match": {"value": document_id},
                    }]
                }
            },
        )
        response.raise_for_status()

    def _upsert(self, work, vectors: list[tuple[float, ...]]) -> None:
        if len(vectors) != len(work.chunks):
            raise RuntimeError("vector/chunk count mismatch")
        points = []
        for chunk, vector in zip(work.chunks, vectors, strict=True):
            point_id = str(uuid.uuid5(uuid.NAMESPACE_URL, chunk.chunk_id))
            points.append({
                "id": point_id,
                "vector": {self.profile.vector_name: list(vector)},
                "payload": {
                    "text": chunk.text,
                    "domain": work.source.domain,
                    "namespace": work.source.namespace,
                    "source_type": work.source.source_type,
                    "source_uri": work.document.uri,
                    "source_title": work.document.title,
                    "source_id": work.source.source_id,
                    "document_id": work.document_id,
                    "version_id": work.version_id,
                    "chunk_id": chunk.chunk_id,
                    "chunk_profile": chunk.chunk_profile,
                    "chunk_ordinal": chunk.ordinal,
                    "content_sha256": work.version.content_sha256,
                    "source_revision": work.version.source_revision,
                    **dict(chunk.locator),
                },
            })
        for start in range(0, len(points), 64):
            response = self._client.put(
                f"/collections/{self.profile.collection}/points",
                params={"wait": "true"},
                json={"points": points[start:start + 64]},
            )
            response.raise_for_status()
