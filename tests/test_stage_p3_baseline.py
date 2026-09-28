import json
from pathlib import Path

from ai_bridge.benchmarks.contracts import GoldenCase
from ai_bridge.benchmarks.matrix import BaselineMatrix
from ai_bridge.benchmarks.resources import (
    ResourcePoint,
    ResourceSampler,
)
from ai_bridge.benchmarks.router_gliner import GlinerDecisionAdapter


ROOT = Path(__file__).resolve().parents[1]


def _router_case():
    return GoldenCase.model_validate({
        "schema_version": 1,
        "case_id": "ERS-GOLD-P3",
        "targets": ["router"],
        "question": "Sprawdź dokumentację tego numeru części.",
        "query_variants": [],
        "context_turns": [
            {"role": "user", "content": "Chodzi o sterownik silnika."},
        ],
        "category": "router",
        "difficulty": "easy",
        "language": "pl",
        "split": "dev",
        "training_exclusion": True,
        "expected_facts": [
            {"fact_id": "f1", "statement": "Knowledge route.", "required": True},
        ],
        "expected_evidence": [{
            "source_id": "POLICY",
            "locator": "benchmarks/automotive_v1/suites/router.json",
            "supports_fact_ids": ["f1"],
        }],
        "acceptable_answer": {
            "reference": "knowledge",
            "required_concepts": ["knowledge"],
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
            "must_cite": False,
            "minimum_source_coverage": 0.0,
            "fail_closed_if_missing": True,
        },
        "expected_confidence": {"grounded_min": 0.8, "ungrounded_max": 0.2},
        "provenance": {
            "source_repo": "autoklinika/AI-server",
            "source_ids": ["POLICY"],
            "case_ids": [],
            "reuse_status": "project_owned_policy",
        },
        "tags": ["router"],
    })


def test_p3_matrix_forbids_training_and_gates_splits():
    matrix = BaselineMatrix.load(
        ROOT / "benchmarks" / "automotive_v1" / "p3_baseline_matrix.json"
    )
    assert matrix.policy.training_allowed is False
    assert matrix.policy.holdout_after_dev_gate is True
    assert matrix.policy.challenge_after_holdout_gate is True
    assert [phase.split for phase in matrix.phases[-2:]] == ["holdout", "challenge"]
    dev_runs = [
        run
        for phase in matrix.phases
        if phase.split == "dev"
        for run in phase.runs
    ]
    assert {run.track for run in dev_runs} >= {
        "retrieval_only",
        "retrieval_plus_reranker",
        "reasoning_fixed_evidence",
        "end_to_end_rag",
        "routing_zero_shot",
    }
    assert all(run.subject_kind and run.adapter for run in dev_runs)
    router_runs = [run for run in dev_runs if run.suite == "decision-models"]
    assert all(run.adapter == "router-adapter-v1" for run in router_runs)
    assert all(run.parameters["map_location"] == "cpu" for run in router_runs)


def test_gliner_adapter_uses_independent_route_and_tool_heads():
    seen = {}

    class FakeExtractor:
        def classify_text(self, text, tasks):
            seen["text"] = text
            seen["tasks"] = tasks
            return {
                "route": "knowledge_rag",
                "tools": ["knowledge.search", "none"],
            }

    decision = GlinerDecisionAdapter(
        "fake/model",
        extractor=FakeExtractor(),
    ).decide(_router_case())

    assert decision.route == "knowledge_rag"
    assert decision.selected_tools == ["knowledge.search"]
    assert "Chodzi o sterownik silnika." in seen["text"]
    assert "Sprawdź dokumentację" in seen["text"]
    assert seen["tasks"]["tools"]["multi_label"] is True
    assert decision.latency_ms >= 0
    assert decision.peak_ram_bytes is None or decision.peak_ram_bytes > 0


def test_resource_sampler_reports_system_peak_delta():
    points = iter([
        ResourcePoint(ram_used_bytes=100, vram_used_bytes=200),
        ResourcePoint(ram_used_bytes=150, vram_used_bytes=260),
        ResourcePoint(ram_used_bytes=120, vram_used_bytes=230),
    ])

    def reader():
        try:
            return next(points)
        except StopIteration:
            return ResourcePoint(ram_used_bytes=120, vram_used_bytes=230)

    sampler = ResourceSampler(interval_ms=1000, reader=reader).start()
    sampler._points.append(reader())
    usage = sampler.stop()

    assert usage.scope == "system"
    assert usage.baseline.ram_used_bytes == 100
    assert usage.peak.ram_used_bytes == 150
    assert usage.peak_delta_ram_bytes == 50
    assert usage.peak_delta_vram_bytes == 60
