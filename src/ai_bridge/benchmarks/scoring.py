"""Deterministic scoring over normalized benchmark observations."""
from __future__ import annotations

import math
from statistics import mean

from pydantic import Field

from .contracts import GoldenCase, GoldenDataset, StrictModel, Target


class BenchmarkObservation(StrictModel):
    case_id: str
    matched_fact_ids: list[str] = Field(default_factory=list)
    cited_source_ids: list[str] = Field(default_factory=list)
    forbidden_claims_triggered: list[str] = Field(default_factory=list)
    route: str | None = None
    selected_tools: list[str] = Field(default_factory=list)
    ranked_source_ids: list[str] = Field(default_factory=list)
    fail_closed: bool = False
    latency_ms: float | None = Field(default=None, ge=0)
    peak_ram_bytes: int | None = Field(default=None, ge=0)
    peak_vram_bytes: int | None = Field(default=None, ge=0)
    throughput_tps: float | None = Field(default=None, ge=0)


def _ratio(found: set[str], expected: set[str]) -> float:
    if not expected:
        return 1.0
    return len(found & expected) / len(expected)


def _ndcg_at_k(ranked: list[str], relevant: set[str], k: int) -> float:
    if not relevant:
        return 1.0
    dcg = 0.0
    for index, source_id in enumerate(ranked[:k], start=1):
        if source_id in relevant:
            dcg += 1.0 / math.log2(index + 1)
    ideal_hits = min(len(relevant), k)
    idcg = sum(1.0 / math.log2(index + 1) for index in range(1, ideal_hits + 1))
    return dcg / idcg if idcg else 1.0


def score_observation(case: GoldenCase, obs: BenchmarkObservation) -> dict[str, float]:
    required_facts = {fact.fact_id for fact in case.expected_facts if fact.required}
    expected_sources = {evidence.source_id for evidence in case.expected_evidence}
    expected_tools = set(case.expected_routing.expected_tools)
    ranked = obs.ranked_source_ids
    first_rank = next(
        (index for index, source in enumerate(ranked, 1) if source in expected_sources),
        None,
    )

    metrics = {
        "fact_recall": _ratio(set(obs.matched_fact_ids), required_facts),
        "forbidden_claim_rate": 1.0 if obs.forbidden_claims_triggered else 0.0,
        "citation_recall": _ratio(set(obs.cited_source_ids), expected_sources),
        "route_accuracy": 1.0 if obs.route == case.expected_routing.primary else 0.0,
        "tool_selection_recall": _ratio(set(obs.selected_tools), expected_tools),
        "evidence_recall_at_1": _ratio(set(ranked[:1]), expected_sources),
        "evidence_recall_at_3": _ratio(set(ranked[:3]), expected_sources),
        "evidence_recall_at_5": _ratio(set(ranked[:5]), expected_sources),
        "mrr": 0.0 if first_rank is None else 1.0 / first_rank,
        "ndcg_at_5": _ndcg_at_k(ranked, expected_sources, 5),
    }
    if "fail-closed" in case.tags:
        metrics["fail_closed_accuracy"] = 1.0 if obs.fail_closed else 0.0
    return metrics


def aggregate(
    dataset: GoldenDataset,
    observations: list[BenchmarkObservation],
    target: Target,
) -> dict:
    by_id = {obs.case_id: obs for obs in observations}
    cases = [case for case in dataset.cases if target in case.targets]
    missing = [case.case_id for case in cases if case.case_id not in by_id]
    if missing:
        raise ValueError(f"missing observations: {missing}")

    scored = [(case, by_id[case.case_id], score_observation(case, by_id[case.case_id]))
              for case in cases]
    metric_names = sorted({name for _, _, metrics in scored for name in metrics})
    metrics = {
        name: mean(item[name] for _, _, item in scored if name in item)
        for name in metric_names
    }
    resources = {}
    for field in ("latency_ms", "peak_ram_bytes", "peak_vram_bytes", "throughput_tps"):
        values = [getattr(obs, field) for _, obs, _ in scored if getattr(obs, field) is not None]
        if values:
            resources[field] = {
                "mean": mean(values),
                "max": max(values),
            }
    return {
        "schema_version": 1,
        "benchmark_class": target,
        "case_count": len(cases),
        "metrics": metrics,
        "resources": resources,
        "case_scores": [
            {"case_id": case.case_id, "metrics": score}
            for case, _, score in scored
        ],
    }
