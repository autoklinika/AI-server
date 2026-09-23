from ai_bridge.knowledge.rerank import TechnicalEvidenceReranker
from ai_bridge.providers.contracts import KnowledgeQuery, KnowledgeResult, KnowledgeSource


def hit(result_id, text, score):
    return KnowledgeResult(
        result_id=result_id,
        text=text,
        source=KnowledgeSource(type="documentation", uri=f"repo://{result_id}"),
        score=score,
        metadata={"chunk_id": result_id},
    )


def test_technical_reranker_promotes_literal_identifiers():
    query = KnowledgeQuery(
        request_id="r",
        domain="ecu-repair",
        query="0 281 007 439 SPN 107 FMI 3",
        mode="hybrid",
        limit=2,
    )
    semantic_first = hit("semantic", "General SPN diagnostics for air pressure sensor.", 0.99)
    literal_second = hit(
        "literal",
        "Bosch 0 281 007 439 appears in CASE SPN 107 FMI 3.",
        0.80,
    )
    ranked = TechnicalEvidenceReranker().rerank(
        query,
        (semantic_first, literal_second),
        limit=2,
    )
    assert ranked[0].result_id == "literal"
    assert ranked[0].metadata["rerank"]["identifier_coverage"] > 0
    assert ranked[0].metadata["rerank"]["original_rank"] == 2
