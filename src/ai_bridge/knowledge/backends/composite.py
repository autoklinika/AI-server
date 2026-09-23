from __future__ import annotations

from dataclasses import replace
from time import monotonic

from ai_bridge.providers.contracts import (
    KnowledgeBackend,
    KnowledgeQuery,
    KnowledgeResult,
    KnowledgeSearchResult,
    ProviderDescriptor,
    ProviderHealth,
)


class CompositeKnowledgeBackend:
    """Stable exact/keyword/semantic/hybrid router with rank fusion."""

    def __init__(
        self,
        *,
        dense: KnowledgeBackend,
        lexical: KnowledgeBackend,
        logical_backend_id: str = "knowledge-primary",
        rrf_k: int = 60,
    ) -> None:
        if rrf_k < 1:
            raise ValueError("rrf_k must be positive")
        self.dense = dense
        self.lexical = lexical
        self.logical_backend_id = logical_backend_id
        self.rrf_k = rrf_k

    def health(self) -> ProviderHealth:
        dense = self.dense.health()
        lexical = self.lexical.health()
        if dense.status == "ready" and lexical.status == "ready":
            return ProviderHealth(status="ready")
        if dense.status != "unavailable" or lexical.status != "unavailable":
            return ProviderHealth(
                status="degraded",
                detail=f"dense={dense.status},lexical={lexical.status}",
            )
        return ProviderHealth(
            status="unavailable",
            detail=f"dense={dense.status},lexical={lexical.status}",
        )

    def describe(self) -> ProviderDescriptor:
        health = self.health()
        return ProviderDescriptor(
            provider_id=self.logical_backend_id,
            provider_type="knowledge-backend",
            node_id=None,
            capabilities=(
                "exact",
                "keyword",
                "semantic",
                "hybrid",
                "metadata-filtering",
                "source-attribution",
            ),
            models=(),
            status=health.status,
            metadata={"fusion": "rrf-v1"},
        )

    def search(self, query: KnowledgeQuery) -> KnowledgeSearchResult:
        if query.mode == "semantic":
            return self._relabel(self.dense.search(query))
        if query.mode in {"exact", "keyword"}:
            return self._relabel(self.lexical.search(query))
        if query.mode not in {"hybrid", "auto"}:
            raise ValueError("unsupported knowledge query mode")

        started = monotonic()
        candidate_limit = min(100, max(query.limit * 4, 20))
        dense_query = replace(query, mode="semantic", limit=candidate_limit)
        lexical_query = replace(
            query,
            mode="keyword",
            limit=candidate_limit,
            query_embedding=None,
        )
        dense_result = self.dense.search(dense_query)
        lexical_result = self.lexical.search(lexical_query)
        fused = self._fuse(
            dense_result.results,
            lexical_result.results,
            limit=query.limit,
        )
        return KnowledgeSearchResult(
            request_id=query.request_id,
            results=fused,
            backend=self.logical_backend_id,
            duration_ms=(monotonic() - started) * 1000.0,
            backend_metadata={
                "contract_version": 1,
                "fusion": "rrf-v1",
                "dense_candidates": len(dense_result.results),
                "lexical_candidates": len(lexical_result.results),
            },
        )

    def _relabel(self, result: KnowledgeSearchResult) -> KnowledgeSearchResult:
        return replace(
            result,
            backend=self.logical_backend_id,
            backend_metadata={
                **result.backend_metadata,
                "contract_version": 1,
            },
        )

    def _fuse(
        self,
        dense: tuple[KnowledgeResult, ...],
        lexical: tuple[KnowledgeResult, ...],
        *,
        limit: int,
    ) -> tuple[KnowledgeResult, ...]:
        scores: dict[str, float] = {}
        exemplars: dict[str, KnowledgeResult] = {}
        ranks: dict[str, dict[str, int]] = {}

        for channel, results in (("dense", dense), ("lexical", lexical)):
            for rank, hit in enumerate(results, start=1):
                key = str(hit.metadata.get("chunk_id") or hit.result_id)
                scores[key] = scores.get(key, 0.0) + 1.0 / (self.rrf_k + rank)
                exemplars.setdefault(key, hit)
                ranks.setdefault(key, {})[channel] = rank

        ordered = sorted(scores, key=lambda key: (-scores[key], key))
        fused: list[KnowledgeResult] = []
        for key in ordered[:limit]:
            hit = exemplars[key]
            metadata = dict(hit.metadata)
            metadata["fusion"] = {
                "method": "rrf-v1",
                "dense_rank": ranks[key].get("dense"),
                "lexical_rank": ranks[key].get("lexical"),
            }
            fused.append(replace(hit, score=scores[key], metadata=metadata))
        return tuple(fused)
