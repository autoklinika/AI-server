"""Deterministic scoring over normalized benchmark observations."""
from __future__ import annotations

import math
from statistics import mean

from pydantic import Field

from .contracts import GoldenCase, GoldenDataset, StrictModel, Target


class ObservedEvidenceHit(StrictModel):
    rank: int = Field(ge=1)
    supports_fact_ids: list[str] = Field(min_length=1)
    result_id: str | None = None


class BenchmarkObservation(StrictModel):
    case_id: str
    matched_fact_ids: list[str] = Field(default_factory=list)
    evidence_hits: list[ObservedEvidenceHit] = Field(default_factory=list)
    citation_supported_fact_ids: list[str] = Field(default_factory=list)
    citation_count: int | None = Field(default=None, ge=0)
    unsupported_citation_count: int | None = Field(default=None, ge=0)
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


def _evidence_fact_coverage(
    obs: BenchmarkObservation,
    required_facts: set[str],
    k: int,
) -> float:
    covered = {
        fact_id
        for hit in obs.evidence_hits
        if hit.rank <= k
        for fact_id in hit.supports_fact_ids
    }
    return _ratio(covered, required_facts)


def _evidence_fact_ndcg(
    obs: BenchmarkObservation,
    required_facts: set[str],
    k: int,
) -> float:
    if not required_facts:
        return 1.0
    seen: set[str] = set()
    dcg = 0.0
    for hit in sorted(obs.evidence_hits, key=lambda item: item.rank):
        if hit.rank > k:
            continue
        new = (set(hit.supports_fact_ids) & required_facts) - seen
        if new:
            gain = len(new) / len(required_facts)
            dcg += gain / math.log2(hit.rank + 1)
            seen.update(new)
    return min(1.0, dcg)


def score_observation(case: GoldenCase, obs: BenchmarkObservation) -> dict[str, float]:
    required_facts = {fact.fact_id for fact in case.expected_facts if fact.required}
    expected_sources = {evidence.source_id for evidence in case.expected_evidence}
    expected_tools = set(case.expected_routing.expected_tools)
    ranked = obs.ranked_source_ids

    if obs.evidence_hits:
        first_rank = min(hit.rank for hit in obs.evidence_hits)
        evidence_at_1 = _evidence_fact_coverage(obs, required_facts, 1)
        evidence_at_3 = _evidence_fact_coverage(obs, required_facts, 3)
        evidence_at_5 = _evidence_fact_coverage(obs, required_facts, 5)
        ndcg_at_5 = _evidence_fact_ndcg(obs, required_facts, 5)
        relevant_ranks = {hit.rank for hit in obs.evidence_hits}
        denominator = len(ranked) or max(relevant_ranks)
        source_precision = len(relevant_ranks) / denominator if denominator else 0.0
    else:
        first_rank = next(
            (index for index, source in enumerate(ranked, 1) if source in expected_sources),
            None,
        )
        evidence_at_1 = _ratio(set(ranked[:1]), expected_sources)
        evidence_at_3 = _ratio(set(ranked[:3]), expected_sources)
        evidence_at_5 = _ratio(set(ranked[:5]), expected_sources)
        ndcg_at_5 = _ndcg_at_k(ranked, expected_sources, 5)
        relevant = sum(source in expected_sources for source in ranked)
        source_precision = relevant / len(ranked) if ranked else 0.0

    if obs.citation_count is not None:
        unsupported = min(
            obs.unsupported_citation_count or 0,
            obs.citation_count,
        )
        citation_precision = (
            (obs.citation_count - unsupported) / obs.citation_count
            if obs.citation_count
            else (0.0 if case.grounding.must_cite else 1.0)
        )
        citation_recall = _ratio(
            set(obs.citation_supported_fact_ids),
            required_facts,
        )
    else:
        cited = set(obs.cited_source_ids)
        supported = cited & expected_sources
        citation_precision = (
            len(supported) / len(cited)
            if cited else (0.0 if case.grounding.must_cite else 1.0)
        )
        citation_recall = _ratio(supported, expected_sources)

    selected_tools = set(obs.selected_tools)
    extra_tools = selected_tools - expected_tools
    tool_false_positive_rate = (
        len(extra_tools) / len(selected_tools) if selected_tools else 0.0
    )
    metrics = {
        "fact_recall": _ratio(set(obs.matched_fact_ids), required_facts),
        "forbidden_claim_rate": 1.0 if obs.forbidden_claims_triggered else 0.0,
        "citation_precision": citation_precision,
        "citation_recall": citation_recall,
        "grounding_coverage": citation_recall,
        "route_accuracy": 1.0 if obs.route == case.expected_routing.primary else 0.0,
        "tool_selection_recall": _ratio(selected_tools, expected_tools),
        "tool_selection_accuracy": 1.0 if selected_tools == expected_tools else 0.0,
        "false_positive_rate": tool_false_positive_rate,
        "evidence_recall_at_1": evidence_at_1,
        "evidence_recall_at_3": evidence_at_3,
        "evidence_recall_at_5": evidence_at_5,
        "source_precision": source_precision,
        "mrr": 0.0 if first_rank is None else 1.0 / first_rank,
        "ndcg_at_5": ndcg_at_5,
    }
    if "fail-closed" in case.tags:
        metrics["fail_closed_accuracy"] = 1.0 if obs.fail_closed else 0.0
    return metrics


DEFAULT_METRICS: dict[Target, set[str]] = {
    "llm": {
        "fact_recall", "forbidden_claim_rate", "citation_precision",
        "citation_recall", "grounding_coverage", "fail_closed_accuracy",
    },
    "router": {
        "route_accuracy", "macro_f1", "tool_selection_recall",
        "tool_selection_accuracy", "false_positive_rate",
    },
    "retrieval_rag": {
        "evidence_recall_at_1", "evidence_recall_at_3", "evidence_recall_at_5",
        "source_precision", "mrr", "ndcg_at_5",
    },
}


def _macro_f1(cases: list[GoldenCase], by_id: dict[str, BenchmarkObservation]) -> float:
    labels = sorted({
        case.expected_routing.primary for case in cases
    } | {
        by_id[case.case_id].route
        for case in cases
        if by_id[case.case_id].route is not None
    })
    if not labels:
        return 0.0
    scores: list[float] = []
    for label in labels:
        tp = sum(
            case.expected_routing.primary == label
            and by_id[case.case_id].route == label
            for case in cases
        )
        fp = sum(
            case.expected_routing.primary != label
            and by_id[case.case_id].route == label
            for case in cases
        )
        fn = sum(
            case.expected_routing.primary == label
            and by_id[case.case_id].route != label
            for case in cases
        )
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        scores.append(
            2 * precision * recall / (precision + recall)
            if precision + recall else 0.0
        )
    return mean(scores)


def aggregate(
    dataset: GoldenDataset,
    observations: list[BenchmarkObservation],
    target: Target,
    *,
    case_ids: set[str] | None = None,
    metric_names: set[str] | None = None,
) -> dict:
    by_id = {obs.case_id: obs for obs in observations}
    cases = [
        case for case in dataset.cases
        if target in case.targets and (not case_ids or case.case_id in case_ids)
    ]
    missing = [case.case_id for case in cases if case.case_id not in by_id]
    if missing:
        raise ValueError(f"missing observations: {missing}")
    if not cases:
        raise ValueError("no cases selected for aggregation")

    selected_metrics = metric_names or DEFAULT_METRICS[target]
    scored = []
    for case in cases:
        full = score_observation(case, by_id[case.case_id])
        filtered = {
            name: value for name, value in full.items()
            if name in selected_metrics
        }
        scored.append((case, by_id[case.case_id], filtered))

    available = sorted({name for _, _, metrics in scored for name in metrics})
    metrics = {
        name: mean(item[name] for _, _, item in scored if name in item)
        for name in available
    }
    if target == "router" and "macro_f1" in selected_metrics:
        metrics["macro_f1"] = _macro_f1(cases, by_id)
    resources = {}
    for field in ("latency_ms", "peak_ram_bytes", "peak_vram_bytes", "throughput_tps"):
        values = [getattr(obs, field) for _, obs, _ in scored if getattr(obs, field) is not None]
        if values:
            resources[field] = {"mean": mean(values), "max": max(values)}
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
