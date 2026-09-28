from pathlib import Path

from ai_bridge.benchmarks.contracts import GoldenDataset
from ai_bridge.benchmarks.router_adapters import (
    Gliner2RouterAdapter,
    MajorityKnowledgeRouterAdapter,
)
from ai_bridge.benchmarks.scoring import BenchmarkObservation, aggregate


ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "benchmarks" / "automotive_v1" / "datasets" / "golden.v1.jsonl"


def router_cases():
    dataset = GoldenDataset.load_jsonl(DATASET)
    return dataset, [case for case in dataset.cases if "router" in case.targets]


def test_majority_knowledge_floor_exposes_class_imbalance():
    dataset, cases = router_cases()
    adapter = MajorityKnowledgeRouterAdapter()
    observations = []
    for case in cases:
        decision = adapter.decide(case)
        observations.append(BenchmarkObservation(
            case_id=case.case_id,
            route=decision.route,
            selected_tools=decision.selected_tools,
            latency_ms=decision.latency_ms,
        ))
    result = aggregate(dataset, observations, "router")
    assert result["case_count"] == 51
    assert result["metrics"]["route_accuracy"] == 41 / 51
    assert result["metrics"]["tool_selection_accuracy"] == 41 / 51
    assert result["metrics"]["macro_f1"] < 0.2
    assert result["metrics"]["false_positive_rate"] > 0


def test_tool_exact_accuracy_penalizes_extra_tool():
    dataset, cases = router_cases()
    case = next(item for item in cases if item.case_id == "ERS-GOLD-0050")
    result = aggregate(
        dataset,
        [BenchmarkObservation(
            case_id=case.case_id,
            route="reasoning",
            selected_tools=["knowledge.search"],
        )],
        "router",
        case_ids={case.case_id},
    )
    assert result["metrics"]["route_accuracy"] == 1.0
    assert result["metrics"]["tool_selection_recall"] == 1.0
    assert result["metrics"]["tool_selection_accuracy"] == 0.0
    assert result["metrics"]["false_positive_rate"] == 1.0


class FakeExtractor:
    def classify_text(self, text, schema):
        assert "route" in schema and "tools" in schema
        assert schema["tools"]["multi_label"] is True
        return {
            "route": "vision",
            "tools": ["vision.analyze", "knowledge.search"],
        }


def test_gliner_adapter_normalizes_route_and_multitool_output():
    _dataset, cases = router_cases()
    case = next(item for item in cases if item.case_id == "ERS-GOLD-0055")
    adapter = Gliner2RouterAdapter(
        "fake/checkpoint", extractor=FakeExtractor(), threshold=0.4
    )
    decision = adapter.decide(case)
    assert decision.route == "vision"
    assert decision.selected_tools == ["vision.analyze", "knowledge.search"]
    assert decision.latency_ms >= 0
    assert decision.peak_ram_bytes > 0


def test_gliner_adapter_records_revision_with_injected_extractor():
    adapter = Gliner2RouterAdapter(
        "fastino/example",
        revision="0123456789abcdef",
        extractor=FakeExtractor(),
    )
    assert adapter.checkpoint == "fastino/example"
    assert adapter.revision == "0123456789abcdef"
