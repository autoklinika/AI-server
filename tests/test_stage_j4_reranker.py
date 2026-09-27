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


def test_technical_reranker_promotes_matching_document_identity():
    query = KnowledgeQuery(
        request_id="r2",
        domain="ecu-repair",
        query="Jaki procesor jest w sterowniku Scania S6?",
        mode="hybrid",
        limit=2,
    )
    generic = KnowledgeResult(
        result_id="manual",
        text="MPC555 timing and TPU reference material.",
        source=KnowledgeSource(type="documentation", uri="repo://sources/nxp/MPC555/manual.pdf", title="MPC555 manual"),
        score=0.99,
        metadata={"chunk_id": "manual"},
    )
    case = KnowledgeResult(
        result_id="case",
        text="Badane ECU mają wspólny hardware i MCU MPC555LF8MZP40.",
        source=KnowledgeSource(type="github", uri="repo://cases/scania/EMS-S6/README.md", title="Scania EMS S6 — wiedza warsztatowa"),
        score=0.5,
        metadata={"chunk_id": "case", "repository_path": "ecus/scania/EMS-S6/README.md"},
    )
    ranked = TechnicalEvidenceReranker().rerank(query, (generic, case), limit=2)
    assert ranked[0].result_id == "case"
    assert ranked[0].metadata["rerank"]["method"] == "technical-evidence-v2"
    assert ranked[0].metadata["rerank"]["source_token_coverage"] > 0
