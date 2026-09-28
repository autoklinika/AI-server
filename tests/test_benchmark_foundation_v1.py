import json
from pathlib import Path

import pytest

from ai_bridge.benchmarks.contracts import GoldenCase, GoldenDataset, SuiteManifest
from ai_bridge.benchmarks.scoring import BenchmarkObservation, aggregate, score_observation


ROOT = Path(__file__).resolve().parents[1]
BENCH = ROOT / "benchmarks" / "automotive_v1"
DATASET = BENCH / "datasets" / "golden.v1.jsonl"


def test_golden_dataset_v1_is_valid_and_cross_domain():
    dataset = GoldenDataset.load_jsonl(DATASET)
    summary = dataset.summary()
    assert summary["case_count"] >= 14
    assert summary["by_target"]["llm"] >= 10
    assert summary["by_target"]["router"] >= 8
    assert summary["by_target"]["retrieval_rag"] >= 12
    assert summary["by_language"]["pl"] >= 10
    assert summary["by_language"]["en"] >= 2
    assert len(summary["by_category"]) >= 10
    assert summary["by_split"] == {"dev": 14}
    assert all(case.training_exclusion is True for case in dataset.cases)


def test_golden_dataset_is_model_independent():
    text = DATASET.read_text(encoding="utf-8").casefold()
    for model_name in ("qwen", "llama", "mistral", "gliner"):
        assert model_name not in text


def test_suite_manifests_keep_three_benchmark_classes_separate():
    manifests = [
        SuiteManifest.load(path)
        for path in sorted((BENCH / "suites").glob("*.json"))
    ]
    assert {item.benchmark_class for item in manifests} == {
        "llm", "router", "retrieval_rag"
    }
    router = next(item for item in manifests if item.benchmark_class == "router")
    assert router.candidate_models == [
        "fastino/GLiNER2.5-Decide (340M)",
        "fastino/GLiNER2.5-multi-Decide (287M)",
        "fastino/gliner2.5-small-v1 (74M)",
    ]


def test_required_fact_without_evidence_fails_closed():
    payload = json.loads(DATASET.read_text(encoding="utf-8").splitlines()[0])
    payload["expected_evidence"][0]["supports_fact_ids"] = ["f1"]
    with pytest.raises(ValueError, match="required facts without evidence"):
        GoldenCase.model_validate(payload)


def test_retrieval_scoring_uses_source_identity_not_filename_guessing():
    dataset = GoldenDataset.load_jsonl(DATASET)
    case = next(item for item in dataset.cases if item.case_id == "ERS-GOLD-0005")
    obs = BenchmarkObservation(
        case_id=case.case_id,
        matched_fact_ids=["f1", "f2"],
        cited_source_ids=["ERS-DK-0017"],
        route="knowledge_rag",
        selected_tools=["knowledge.search"],
        ranked_source_ids=["noise-source", "ERS-DK-0017"],
        latency_ms=12.5,
    )
    score = score_observation(case, obs)
    assert score["fact_recall"] == 1.0
    assert score["citation_recall"] == 1.0
    assert score["evidence_recall_at_1"] == 0.0
    assert score["evidence_recall_at_3"] == 1.0
    assert score["mrr"] == 0.5


def test_aggregate_requires_complete_target_observations():
    dataset = GoldenDataset.load_jsonl(DATASET)
    with pytest.raises(ValueError, match="missing observations"):
        aggregate(dataset, [], "router")


def test_fail_closed_case_is_explicitly_scored():
    dataset = GoldenDataset.load_jsonl(DATASET)
    case = next(item for item in dataset.cases if item.case_id == "ERS-GOLD-0010")
    obs = BenchmarkObservation(
        case_id=case.case_id,
        matched_fact_ids=["f1", "f2"],
        cited_source_ids=["ERS-ROOT-RULE"],
        route="knowledge_rag",
        selected_tools=["knowledge.search"],
        ranked_source_ids=["ERS-ROOT-RULE"],
        fail_closed=True,
    )
    assert score_observation(case, obs)["fail_closed_accuracy"] == 1.0


def test_run_plan_is_reproducible_and_cannot_enable_training():
    from ai_bridge.benchmarks.run_manifest import build_run_plan

    plan = build_run_plan(
        BENCH / "suites" / "llm.json",
        DATASET,
        track="reasoning_fixed_evidence",
        ai_root=ROOT,
    )
    assert len(plan["dataset"]["sha256"]) == 64
    assert plan["track"] == "reasoning_fixed_evidence"
    assert plan["sources"]["ai_server_commit"]
    assert plan["execution_contract"] == {
        "resource_manager_required": True,
        "direct_provider_bypass_allowed": False,
        "baseline_required_before_training": True,
        "training_allowed_by_this_plan": False,
    }


def test_checked_in_json_schema_matches_contract():
    checked_in = json.loads((BENCH / "golden.schema.json").read_text(encoding="utf-8"))
    assert checked_in == GoldenCase.model_json_schema()


def test_benchmark_catalog_projects_foundation_manifests():
    from ai_bridge.benchmarks.service import BenchmarkCatalog

    suites = {
        item["suite_id"]: item
        for item in BenchmarkCatalog(ROOT / "benchmarks").list_suites()
    }
    assert suites["automotive-reasoning"]["status"] == "foundation"
    assert suites["automotive-reasoning"]["case_count"] == 10
    assert suites["decision-models"]["status"] == "foundation"
    assert suites["decision-models"]["case_count"] == 8
    assert suites["rag-knowledge"]["status"] == "foundation"
    assert suites["rag-knowledge"]["case_count"] == 12
    assert suites["vision"]["status"] == "planned"


def test_run_plan_rejects_unknown_track():
    from ai_bridge.benchmarks.run_manifest import build_run_plan

    with pytest.raises(ValueError, match="unsupported track"):
        build_run_plan(
            BENCH / "suites" / "retrieval_rag.json",
            DATASET,
            track="reasoning_fixed_evidence",
            ai_root=ROOT,
        )
