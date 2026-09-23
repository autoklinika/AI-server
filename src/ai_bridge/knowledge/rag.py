from __future__ import annotations

from dataclasses import dataclass
import json

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from ai_bridge.providers.contracts import KnowledgeResult


class RAGClaim(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    text: str = Field(min_length=1, max_length=6000)
    source_refs: list[str] = Field(min_length=1, max_length=8)


class RAGProviderPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    claims: list[RAGClaim] = Field(default_factory=list, max_length=12)
    insufficient_context: bool = False
    insufficiency_reason: str | None = Field(default=None, max_length=4000)

    @model_validator(mode="after")
    def validate_state(self):
        if self.insufficient_context:
            if not self.insufficiency_reason:
                raise ValueError("insufficient context requires reason")
        elif not self.claims:
            raise ValueError("grounded answer requires at least one claim")
        return self

    @property
    def answer(self) -> str:
        if self.claims:
            return "\n".join(claim.text for claim in self.claims)
        return self.insufficiency_reason or "Brak wystarczającej wiedzy."


@dataclass(frozen=True)
class RAGSource:
    ref: str
    result: KnowledgeResult


@dataclass(frozen=True)
class RAGPrompt:
    messages: list[dict[str, str]]
    response_schema: dict
    sources: tuple[RAGSource, ...]


def build_rag_prompt(
    *,
    question: str,
    results: tuple[KnowledgeResult, ...],
    max_sources: int = 8,
    max_context_chars: int = 24000,
) -> RAGPrompt:
    if not question.strip():
        raise ValueError("question is required")
    if max_sources < 1 or max_context_chars < 1000:
        raise ValueError("invalid RAG limits")

    chosen: list[RAGSource] = []
    blocks: list[str] = []
    used = 0
    for index, result in enumerate(results[:max_sources], start=1):
        ref = f"S{index}"
        page = result.metadata.get("page")
        locator = f" page={page}" if page is not None else ""
        block = (
            f"[{ref}] source={result.source.uri}{locator}\n"
            f"title={result.source.title or ''}\n"
            f"document_id={result.metadata.get('document_id', '')}\n"
            f"chunk_id={result.metadata.get('chunk_id', result.result_id)}\n"
            f"text:\n{result.text.strip()}\n"
        )
        remaining = max_context_chars - used
        if remaining <= 0:
            break
        if len(block) > remaining:
            block = block[:remaining]
        blocks.append(block)
        chosen.append(RAGSource(ref=ref, result=result))
        used += len(block)
        if used >= max_context_chars:
            break

    source_text = "\n---\n".join(blocks) if blocks else "(no sources)"
    system = (
        "You are the RAG answerer for a technical Knowledge Service. "
        "Use ONLY the provided SOURCE blocks. Never use outside knowledge or guess. "
        "Return a list of claims. Every claim must be fully supported by the "
        "source_refs attached to that same claim; do not use a global citation list. "
        "Do not state that a part was not replaced, a test was performed, or a causal "
        "relationship exists unless a cited source explicitly supports it. "
        "Use only source refs like S1 that were provided. "
        "If evidence is insufficient, set insufficient_context=true, explain what is "
        "missing in insufficiency_reason, and include only claims that are still directly supported. "
        "Prefer exact identifiers, measurements, pins, DTCs and conditions from sources."
    )
    user = f"QUESTION:\n{question.strip()}\n\nSOURCES:\n{source_text}"
    return RAGPrompt(
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        response_schema=RAGProviderPayload.model_json_schema(),
        sources=tuple(chosen),
    )


def parse_rag_response(content: str, prompt: RAGPrompt) -> RAGProviderPayload:
    try:
        raw = json.loads(content)
        parsed = RAGProviderPayload.model_validate(raw)
    except (json.JSONDecodeError, ValidationError) as exc:
        raise ValueError("RAG provider returned invalid structured response") from exc

    allowed = {source.ref for source in prompt.sources}
    for claim in parsed.claims:
        refs = claim.source_refs
        if len(refs) != len(set(refs)):
            raise ValueError("RAG provider returned duplicate source refs")
        if any(ref not in allowed for ref in refs):
            raise ValueError("RAG provider cited unknown source ref")
    return parsed


def referenced_source_refs(parsed: RAGProviderPayload) -> list[str]:
    ordered: list[str] = []
    for claim in parsed.claims:
        for ref in claim.source_refs:
            if ref not in ordered:
                ordered.append(ref)
    return ordered


def claim_payload(parsed: RAGProviderPayload) -> list[dict]:
    return [
        {
            "text": claim.text,
            "source_refs": list(claim.source_refs),
        }
        for claim in parsed.claims
    ]


def citation_payload(prompt: RAGPrompt, refs: list[str]) -> list[dict]:
    by_ref = {source.ref: source.result for source in prompt.sources}
    citations: list[dict] = []
    for ref in refs:
        result = by_ref[ref]
        citations.append({
            "ref": ref,
            "source": {
                "type": result.source.type,
                "uri": result.source.uri,
                "title": result.source.title,
            },
            "document_id": result.metadata.get("document_id"),
            "version_id": result.metadata.get("version_id"),
            "chunk_id": result.metadata.get("chunk_id", result.result_id),
            "page": result.metadata.get("page"),
            "section": result.metadata.get("section"),
            "score": result.score,
            "snippet": result.text[:700],
        })
    return citations
