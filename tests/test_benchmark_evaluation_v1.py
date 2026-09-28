import hashlib
import json
from pathlib import Path

import pytest

from ai_bridge.benchmarks.contracts import GoldenCase, GoldenDataset
from ai_bridge.benchmarks.evaluation import (
    CaseEvaluation,
    EvaluationBundle,
    RelevantResult,
    deterministic_retrieval_bundle,
    finalize_run,
)
from ai_bridge.benchmarks.runner import (
    BenchmarkRunArtifact,
    BenchmarkSubject,
    CaseExecution,
    RetrievedHitArtifact,
)
from ai_bridge.benchmarks.resources import ResourcePoint, SystemResourceUsage


def _case():
    return GoldenCase.model_validate({
        "schema_version": 1,
        "case_id": "ERS-GOLD-EVAL1",
        "targets": ["retrieval_rag"],
        "question": "What is the value?",
        "query_variants": [],
        "context_turns": [],
        "category": "eval",
        "difficulty": "medium",
        "language": "en",
        "split": "dev",
        "training_exclusion": True,
        "expected_facts": [
            {"fact_id": "f1", "statement": "Value is 42.", "required": True},
        ],
        "expected_evidence": [{
            "source_id": "SRC-42",
            "locator": "docs/value.md",
            "supports_fact_ids": ["f1"],
        }],
        "acceptable_answer": {
            "reference": "42",
            "required_concepts": ["42"],
            "optional_concepts": [],
        },
        "forbidden_claims": [],
        "required_tools": ["knowledge.search"],
        "expected_routing": {
            "primary": "knowledge_rag",
            "requires_knowledge": True,
            "requires_graph": False,
            "requires_vision": False,
            "expected_tools": ["knowledge.search"],
        },
        "grounding": {
            "must_cite": True,
            "minimum_source_coverage": 1.0,
            "fail_closed_if_missing": True,
        },
        "expected_confidence": {
            "grounded_min": 0.8,
            "ungrounded_max": 0.2,
        },
        "provenance": {
            "source_repo": "test/repo",
            "source_ids": ["SRC-42"],
            "case_ids": [],
            "reuse_status": "test",
        },
        "tags": ["test"],
    })


def _dataset(tmp_path: Path):
    case = _case()
    path = tmp_path / "golden.jsonl"
    path.write_text(case.model_dump_json() + "\n", encoding="utf-8")
    return case, path, GoldenDataset.load_jsonl(path)


def _artifact(path: Path):
    return BenchmarkRunArtifact(
        run_id="run_eval",
        suite_id="rag-knowledge",
        benchmark_class="retrieval_rag",
        track="retrieval_only",
        subject=BenchmarkSubject(
            subject_id="knowledge-hybrid",
            kind="knowledge-config",
            adapter="knowledge-api-v1",
        ),
        mode="recorded",
        dataset_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        source_revisions={"ai_server_commit": "abc"},
        case_count=1,
        cases=[CaseExecution(
            case_id="ERS-GOLD-EVAL1",
            request_id="req_eval",
            endpoint="/api/v1/knowledge/search",
            status="completed",
            evaluation_state="pending_relevance",
            hits=[RetrievedHitArtifact(
                rank=1,
                result_id="hit-1",
                score=0.9,
                source_uri="github://test/repo/docs/value.md",
                source_title="Value",
                source_id="ksrc-internal",
                repository_path=None,
                text="Value is 42.",
            )],
            throughput_tps=12.5,
            resource_usage=SystemResourceUsage(
                baseline=ResourcePoint(ram_used_bytes=100, vram_used_bytes=200),
                peak=ResourcePoint(ram_used_bytes=150, vram_used_bytes=260),
                final=ResourcePoint(ram_used_bytes=120, vram_used_bytes=230),
                peak_delta_ram_bytes=50,
                peak_delta_vram_bytes=60,
                sample_count=3,
                interval_ms=50.0,
            ),
        )],
    )


def test_deterministic_bundle_maps_locator_to_expected_fact(tmp_path):
    _case_value, path, dataset = _dataset(tmp_path)
    artifact = _artifact(path)
    bundle = deterministic_retrieval_bundle(artifact, dataset)
    assert bundle.evaluator_type == "deterministic"
    assert bundle.cases[0].relevant_results[0].supports_fact_ids == ["f1"]

    result = finalize_run(
        artifact, dataset, bundle, dataset_path=path
    )
    assert result["aggregate"]["metrics"]["evidence_recall_at_1"] == 1.0
    assert result["aggregate"]["resources"]["peak_ram_bytes"]["max"] == 50
    assert result["aggregate"]["resources"]["peak_vram_bytes"]["max"] == 60
    assert result["aggregate"]["resources"]["throughput_tps"]["mean"] == 12.5


def test_evaluation_bundle_cannot_reference_unknown_result(tmp_path):
    _case_value, path, dataset = _dataset(tmp_path)
    artifact = _artifact(path)
    bundle = EvaluationBundle(
        run_id=artifact.run_id,
        evaluator_type="human",
        evaluator_id="reviewer",
        evaluator_version="1",
        cases=[CaseEvaluation(
            case_id="ERS-GOLD-EVAL1",
            relevant_results=[RelevantResult(
                result_id="missing-hit",
                supports_fact_ids=["f1"],
            )],
        )],
    )
    with pytest.raises(ValueError, match="unknown result_id"):
        finalize_run(artifact, dataset, bundle, dataset_path=path)


def test_dataset_hash_lock_rejects_changed_gold(tmp_path):
    _case_value, path, dataset = _dataset(tmp_path)
    artifact = _artifact(path)
    path.write_text(path.read_text() + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="dataset SHA-256 mismatch"):
        finalize_run(
            artifact,
            GoldenDataset.load_jsonl(path),
            deterministic_retrieval_bundle(artifact, dataset),
            dataset_path=path,
        )
