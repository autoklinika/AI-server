from __future__ import annotations

from dataclasses import replace
import re

from ai_bridge.providers.contracts import KnowledgeQuery, KnowledgeResult


_TOKEN = re.compile(r"[\w]+(?:[-./:+][\w]+)*", re.UNICODE)
_QUERY_NOISE = {
    "a", "co", "czy", "do", "i", "ile", "in", "is", "jaka", "jaki", "jakie",
    "jest", "ma", "na", "of", "procesor", "processor", "mcu", "sterownik",
    "sterowniku", "controller", "ecu", "the", "to", "w", "we", "what", "which",
    "z", "za", "znajduje", "się",
}


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

def _source_descriptor(hit: KnowledgeResult) -> str:
    fields = (
        hit.source.title or "",
        hit.source.uri or "",
        str(hit.metadata.get("repository_path") or ""),
        str(hit.metadata.get("section") or ""),
    )
    return " ".join(field for field in fields if field)


class TechnicalEvidenceReranker:
    """Deterministic reranker favoring literal evidence and source identity."""

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
        significant = tuple(
            token for token in query_tokens
            if token not in _QUERY_NOISE and len(token) > 1
        ) or query_tokens
        identifiers = _identifiers(tuple(_TOKEN.findall(query.query)))
        folded_query = " ".join(query.query.casefold().split())
        scored: list[tuple[float, int, KnowledgeResult]] = []

        for rank, hit in enumerate(results, start=1):
            content_tokens = set(_tokens(hit.text))
            source_descriptor = _source_descriptor(hit)
            source_tokens = set(_tokens(source_descriptor))
            combined_folded = " ".join(
                (hit.text + "\n" + source_descriptor).casefold().split()
            )
            folded_content = " ".join(hit.text.casefold().split())
            folded_source = " ".join(source_descriptor.casefold().split())

            token_coverage = (
                sum(token in content_tokens for token in set(query_tokens))
                / max(1, len(set(query_tokens)))
            )
            evidence_token_coverage = (
                sum(token in content_tokens for token in set(significant))
                / max(1, len(set(significant)))
            )
            source_token_coverage = (
                sum(token in source_tokens for token in set(significant))
                / max(1, len(set(significant)))
            )
            identifier_coverage = (
                sum(identifier.casefold() in combined_folded for identifier in identifiers)
                / max(1, len(identifiers))
                if identifiers else 0.0
            )
            phrase = 1.0 if folded_query and folded_query in folded_content else 0.0
            source_phrase = 1.0 if folded_query and folded_query in folded_source else 0.0
            base = 1.0 / rank
            score = (
                base
                + 0.35 * token_coverage
                + 0.55 * evidence_token_coverage
                + 1.35 * source_token_coverage
                + 1.35 * identifier_coverage
                + 0.75 * phrase
                + 1.25 * source_phrase
            )

            metadata = dict(hit.metadata)
            metadata["rerank"] = {
                "method": "technical-evidence-v2",
                "original_rank": rank,
                "token_coverage": round(token_coverage, 6),
                "evidence_token_coverage": round(evidence_token_coverage, 6),
                "source_token_coverage": round(source_token_coverage, 6),
                "identifier_coverage": round(identifier_coverage, 6),
                "phrase_match": bool(phrase),
                "source_phrase_match": bool(source_phrase),
            }
            scored.append((score, rank, replace(hit, score=score, metadata=metadata)))

        scored.sort(key=lambda item: (-item[0], item[1], item[2].result_id))
        return tuple(item[2] for item in scored[:limit])
