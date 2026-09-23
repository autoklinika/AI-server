from __future__ import annotations

from collections import Counter
import math
import re
from time import monotonic
from typing import Any

from sqlalchemy.exc import SQLAlchemyError

from ai_bridge.knowledge.storage.repository import (
    CanonicalSearchChunk,
    KnowledgeRepository,
)
from ai_bridge.providers.contracts import (
    KnowledgeQuery,
    KnowledgeResult,
    KnowledgeSearchResult,
    KnowledgeSource,
    ProviderDescriptor,
    ProviderHealth,
)


_TOKEN = re.compile(r"[\w]+(?:[-./:+][\w]+)*", re.UNICODE)


def _tokens(text: str) -> tuple[str, ...]:
    return tuple(token.casefold() for token in _TOKEN.findall(text))


class CanonicalLexicalKnowledgeBackend:
    """Exact/keyword retrieval over current canonical chunks."""

    def __init__(
        self,
        repository: KnowledgeRepository,
        *,
        logical_backend_id: str = "knowledge-lexical",
        candidate_limit: int = 5000,
    ) -> None:
        self.repository = repository
        self.logical_backend_id = logical_backend_id
        self.candidate_limit = candidate_limit

    def health(self) -> ProviderHealth:
        try:
            self.repository._database.ping()
            return ProviderHealth(status="ready")
        except SQLAlchemyError as exc:
            return ProviderHealth(status="unavailable", detail=type(exc).__name__)

    def describe(self) -> ProviderDescriptor:
        health = self.health()
        return ProviderDescriptor(
            provider_id=self.logical_backend_id,
            provider_type="knowledge-backend",
            node_id=None,
            capabilities=("exact", "keyword", "metadata-filtering", "source-attribution"),
            models=(),
            status=health.status,
            metadata={"scoring": "bm25-canonical-v1"},
        )

    def search(self, query: KnowledgeQuery) -> KnowledgeSearchResult:
        if query.mode not in {"exact", "keyword"}:
            raise ValueError("lexical backend supports exact/keyword modes only")
        started = monotonic()
        candidates = self.repository.current_chunks(
            domain=query.domain,
            namespaces=query.namespaces,
            source_types=query.source_types,
            limit=self.candidate_limit,
        )
        candidates = tuple(
            item for item in candidates if self._matches_filters(item, query.filters)
        )
        ranked = self._rank(query.query, candidates, exact=query.mode == "exact")
        results = tuple(
            KnowledgeResult(
                result_id=item.chunk_id,
                text=item.text,
                source=KnowledgeSource(
                    type=item.source_type,
                    uri=item.source_uri,
                    title=item.source_title,
                ),
                score=score,
                metadata=item.metadata,
            )
            for score, item in ranked[:query.limit]
        )
        return KnowledgeSearchResult(
            request_id=query.request_id,
            results=results,
            backend=self.logical_backend_id,
            duration_ms=(monotonic() - started) * 1000.0,
            backend_metadata={"scoring": "bm25-canonical-v1"},
        )

    @staticmethod
    def _matches_filters(
        item: CanonicalSearchChunk, filters: dict[str, Any]
    ) -> bool:
        values = {
            "domain": item.domain,
            "namespace": item.namespace,
            "source_type": item.source_type,
            **item.metadata,
        }
        for key, expected in filters.items():
            actual = values.get(key)
            if isinstance(expected, (list, tuple)):
                if actual not in expected:
                    return False
            elif actual != expected:
                return False
        return True

    @staticmethod
    def _rank(
        query_text: str,
        candidates: tuple[CanonicalSearchChunk, ...],
        *,
        exact: bool,
    ) -> list[tuple[float, CanonicalSearchChunk]]:
        query_terms = _tokens(query_text)
        if not query_terms or not candidates:
            return []

        tokenized = [Counter(_tokens(item.text)) for item in candidates]
        lengths = [sum(counter.values()) for counter in tokenized]
        avgdl = sum(lengths) / max(1, len(lengths))
        document_frequency = {
            term: sum(term in counter for counter in tokenized)
            for term in set(query_terms)
        }
        folded_query = " ".join(query_text.casefold().split())
        scored: list[tuple[float, CanonicalSearchChunk]] = []

        for item, counts, length in zip(candidates, tokenized, lengths, strict=True):
            folded_text = " ".join(item.text.casefold().split())
            phrase_match = folded_query in folded_text
            if exact and not (
                phrase_match or all(term in counts for term in query_terms)
            ):
                continue

            score = 0.0
            for term in query_terms:
                tf = counts.get(term, 0)
                if not tf:
                    continue
                df = document_frequency[term]
                idf = math.log(1.0 + (len(candidates) - df + 0.5) / (df + 0.5))
                k1 = 1.2
                b = 0.75
                denominator = tf + k1 * (1.0 - b + b * length / max(avgdl, 1.0))
                term_score = idf * (tf * (k1 + 1.0)) / denominator
                if any(char.isdigit() for char in term):
                    term_score *= 1.35
                score += term_score

            if phrase_match:
                score += 5.0 if exact else 1.5
            if score > 0:
                scored.append((score, item))

        scored.sort(key=lambda pair: (-pair[0], pair[1].chunk_id))
        return scored
