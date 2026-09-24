from __future__ import annotations

from dataclasses import replace
import re

from ai_bridge.providers.contracts import KnowledgeQuery, KnowledgeResult


_TOKEN = re.compile(r"[\w]+(?:[-./:+][\w]+)*", re.UNICODE)


def _tokens(text: str) -> tuple[str, ...]:
    return tuple(token.casefold() for token in _TOKEN.findall(text))


def _identifiers(tokens: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(
        token for token in tokens
        if any(char.isdigit() for char in token) or (
            len(token) >= 3 and any(char.isalpha() for char in token)
            and token.upper() == token
        )
    )


class TechnicalEvidenceReranker:
    """Deterministic reranker favoring literal technical evidence."""

    def rerank(
        self,
        query: KnowledgeQuery,
        results: tuple[KnowledgeResult, ...],
        *,
        limit: int,
    ) -> tuple[KnowledgeResult, ...]:
        if limit < 1:
            raise ValueError("limit must be positive")
        query_tokens = _tokens(query.query)
        identifiers = _identifiers(tuple(_TOKEN.findall(query.query)))
        folded_query = " ".join(query.query.casefold().split())
        scored: list[tuple[float, int, KnowledgeResult]] = []

        for rank, hit in enumerate(results, start=1):
            text_tokens = set(_tokens(hit.text))
            folded_text = " ".join(hit.text.casefold().split())
            token_coverage = (
                sum(token in text_tokens for token in query_tokens)
                / max(1, len(set(query_tokens)))
            )
            identifier_coverage = (
                sum(identifier.casefold() in folded_text for identifier in identifiers)
                / max(1, len(identifiers))
                if identifiers else 0.0
            )
            phrase = 1.0 if folded_query and folded_query in folded_text else 0.0
            base = 1.0 / rank
            score = base + 0.75 * token_coverage + 1.25 * identifier_coverage + phrase

            metadata = dict(hit.metadata)
            metadata["rerank"] = {
                "method": "technical-evidence-v1",
                "original_rank": rank,
                "token_coverage": round(token_coverage, 6),
                "identifier_coverage": round(identifier_coverage, 6),
                "phrase_match": bool(phrase),
            }
            scored.append((score, rank, replace(hit, score=score, metadata=metadata)))

        scored.sort(key=lambda item: (-item[0], item[1], item[2].result_id))
        return tuple(item[2] for item in scored[:limit])
