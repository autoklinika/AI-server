import json

import pytest

from ai_bridge.knowledge.rag import (
    build_rag_prompt,
    citation_payload,
    parse_rag_response,
    referenced_source_refs,
)
from ai_bridge.providers.contracts import KnowledgeResult, KnowledgeSource


def hit(index=1):
    return KnowledgeResult(
        result_id=f"kchk_{index}",
        text=f"Evidence {index}: SPN 107 FMI 3 root cause was damaged wire.",
        source=KnowledgeSource(
            type="documentation",
            uri=f"repo://case/{index}.md",
            title=f"Case {index}",
        ),
        score=1.0 / index,
        metadata={
            "document_id": f"kdoc_{index}",
            "version_id": f"kver_{index}",
            "chunk_id": f"kchk_{index}",
            "page": index,
            "section": "Root cause",
        },
    )


def test_rag_prompt_contains_only_bounded_ranked_sources():
    prompt = build_rag_prompt(
        question="Co było przyczyną?",
        results=tuple(hit(i) for i in range(1, 6)),
        max_sources=2,
        max_context_chars=10000,
    )
    assert [item.ref for item in prompt.sources] == ["S1", "S2"]
    assert "S3" not in prompt.messages[1]["content"]
    assert "repo://case/1.md" in prompt.messages[1]["content"]
    assert prompt.response_schema["type"] == "object"


def test_rag_response_requires_per_claim_known_citations():
    prompt = build_rag_prompt(
        question="Co było przyczyną?",
        results=(hit(1), hit(2)),
    )
    valid = parse_rag_response(json.dumps({
        "claims": [{
            "text": "Przyczyną był uszkodzony przewód.",
            "source_refs": ["S1"],
        }],
        "insufficient_context": False,
        "insufficiency_reason": None,
    }), prompt)
    assert valid.answer == "Przyczyną był uszkodzony przewód."
    assert referenced_source_refs(valid) == ["S1"]
    citations = citation_payload(prompt, referenced_source_refs(valid))
    assert citations[0]["document_id"] == "kdoc_1"
    assert citations[0]["page"] == 1

    with pytest.raises(ValueError, match="unknown"):
        parse_rag_response(json.dumps({
            "claims": [{"text": "Invented", "source_refs": ["S99"]}],
            "insufficient_context": False,
            "insufficiency_reason": None,
        }), prompt)


def test_rag_allows_explicit_insufficient_context():
    prompt = build_rag_prompt(question="Unknown?", results=(hit(1),))
    parsed = parse_rag_response(json.dumps({
        "claims": [],
        "insufficient_context": True,
        "insufficiency_reason": "Źródła nie wystarczają do odpowiedzi.",
    }), prompt)
    assert parsed.insufficient_context is True
    assert parsed.answer == "Źródła nie wystarczają do odpowiedzi."
