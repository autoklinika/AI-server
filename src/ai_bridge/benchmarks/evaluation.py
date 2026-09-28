"""Separate semantic/relevance evaluation from benchmark execution."""
from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Literal

from pydantic import Field

from .contracts import GoldenDataset, StrictModel
from .runner import BenchmarkRunArtifact, CaseExecution
from .scoring import (
    BenchmarkObservation,
    ObservedEvidenceHit,
    aggregate,
)


class RelevantResult(StrictModel):
    result_id: str
    supports_fact_ids: list[str] = Field(min_length=1)


class CaseEvaluation(StrictModel):
    case_id: str
    matched_fact_ids: list[str] = Field(default_factory=list)
    relevant_results: list[RelevantResult] = Field(default_factory=list)
    citation_supported_fact_ids: list[str] = Field(default_factory=list)
    unsupported_citation_count: int = Field(default=0, ge=0)
    forbidden_claims_triggered: list[str] = Field(default_factory=list)
    fail_closed: bool = False
    notes: str | None = None


class EvaluationBundle(StrictModel):
    schema_version: Literal[1] = 1
    run_id: str
    evaluator_type: Literal["human", "deterministic", "judge"]
    evaluator_id: str
    evaluator_version: str
    cases: list[CaseEvaluation]


TRACK_METRICS = {
    "reasoning_fixed_evidence": {
        "fact_recall", "forbidden_claim_rate", "citation_precision",
        "citation_recall", "grounding_coverage", "fail_closed_accuracy",
    },
    "closed_book_diagnostic": {
        "fact_recall", "forbidden_claim_rate", "fail_closed_accuracy",
    },
    "tool_use_multiturn": {
        "fact_recall", "forbidden_claim_rate", "citation_precision",
        "citation_recall", "route_accuracy", "tool_selection_recall",
    },
    "retrieval_only": {
        "evidence_recall_at_1", "evidence_recall_at_3", "evidence_recall_at_5",
        "source_precision", "mrr", "ndcg_at_5",
    },
    "retrieval_plus_reranker": {
        "evidence_recall_at_1", "evidence_recall_at_3", "evidence_recall_at_5",
        "source_precision", "mrr", "ndcg_at_5",
    },
    "end_to_end_rag": {
        "fact_recall", "forbidden_claim_rate", "citation_precision",
        "citation_recall", "grounding_coverage", "fail_closed_accuracy",
    },
    "routing_zero_shot": {
        "route_accuracy", "macro_f1", "tool_selection_recall",
        "tool_selection_accuracy", "false_positive_rate",
    },
    "routing_calibrated": {
        "route_accuracy", "macro_f1", "tool_selection_recall",
        "tool_selection_accuracy", "false_positive_rate",
    },
    "routing_finetuned": {
        "route_accuracy", "macro_f1", "tool_selection_recall",
        "tool_selection_accuracy", "false_positive_rate",
    },
}


def _case_lookup(dataset: GoldenDataset) -> dict[str, object]:
    return {case.case_id: case for case in dataset.cases}


def _validate_fact_ids(case, values: list[str], field: str) -> None:
    known = {fact.fact_id for fact in case.expected_facts}
    unknown = sorted(set(values) - known)
    if unknown:
        raise ValueError(f"{case.case_id}: {field} references unknown facts {unknown}")


def _execution_resources(execution: CaseExecution):
    if execution.resource_usage is not None:
        return (
            execution.resource_usage.peak_delta_ram_bytes,
            execution.resource_usage.peak_delta_vram_bytes,
        )
    return execution.peak_ram_bytes, None


def _observation_from_evaluation(
    case,
    execution: CaseExecution,
    evaluation: CaseEvaluation,
) -> BenchmarkObservation:
    _validate_fact_ids(case, evaluation.matched_fact_ids, "matched_fact_ids")
    _validate_fact_ids(
        case,
        evaluation.citation_supported_fact_ids,
        "citation_supported_fact_ids",
    )
    by_result = {hit.result_id: hit for hit in execution.hits}
    evidence_hits: list[ObservedEvidenceHit] = []
    for relevant in evaluation.relevant_results:
        hit = by_result.get(relevant.result_id)
        if hit is None:
            raise ValueError(
                f"{case.case_id}: evaluated unknown result_id {relevant.result_id}"
            )
        _validate_fact_ids(case, relevant.supports_fact_ids, "relevant_results")
        evidence_hits.append(ObservedEvidenceHit(
            rank=hit.rank,
            supports_fact_ids=relevant.supports_fact_ids,
            result_id=relevant.result_id,
        ))

    return BenchmarkObservation(
        case_id=case.case_id,
        matched_fact_ids=evaluation.matched_fact_ids,
        evidence_hits=evidence_hits,
        citation_supported_fact_ids=evaluation.citation_supported_fact_ids,
        citation_count=execution.citation_count,
        unsupported_citation_count=evaluation.unsupported_citation_count,
        cited_source_ids=execution.cited_source_ids,
        forbidden_claims_triggered=evaluation.forbidden_claims_triggered,
        route=execution.route,
        selected_tools=execution.selected_tools,
        ranked_source_ids=[hit.result_id for hit in execution.hits],
        fail_closed=evaluation.fail_closed,
        latency_ms=execution.latency_ms,
        peak_ram_bytes=_execution_resources(execution)[0],
        peak_vram_bytes=_execution_resources(execution)[1],
        throughput_tps=execution.throughput_tps,
    )


def _automatic_observation(case, execution: CaseExecution) -> BenchmarkObservation:
    return BenchmarkObservation(
        case_id=case.case_id,
        route=execution.route,
        selected_tools=execution.selected_tools,
        latency_ms=execution.latency_ms,
        peak_ram_bytes=_execution_resources(execution)[0],
        peak_vram_bytes=_execution_resources(execution)[1],
        throughput_tps=execution.throughput_tps,
    )


def _failed_observation(case, execution: CaseExecution) -> BenchmarkObservation:
    return BenchmarkObservation(
        case_id=case.case_id,
        ranked_source_ids=[hit.result_id for hit in execution.hits],
        latency_ms=execution.latency_ms,
        peak_ram_bytes=_execution_resources(execution)[0],
        peak_vram_bytes=_execution_resources(execution)[1],
        throughput_tps=execution.throughput_tps,
    )


def finalize_run(
    artifact: BenchmarkRunArtifact,
    dataset: GoldenDataset,
    bundle: EvaluationBundle | None,
    *,
    dataset_path: Path | None = None,
) -> dict:
    if artifact.mode == "dry-run":
        raise ValueError("dry-run artifact cannot be evaluated")
    if artifact.case_count != len(artifact.cases):
        raise ValueError("run artifact case_count mismatch")
    if dataset_path is not None:
        current_hash = hashlib.sha256(dataset_path.read_bytes()).hexdigest()
        if current_hash != artifact.dataset_sha256:
            raise ValueError("run artifact dataset SHA-256 mismatch")
    if bundle is not None and bundle.run_id != artifact.run_id:
        raise ValueError("evaluation bundle run_id mismatch")

    cases = _case_lookup(dataset)
    evaluation_items = bundle.cases if bundle else []
    evaluation_ids = [item.case_id for item in evaluation_items]
    if len(evaluation_ids) != len(set(evaluation_ids)):
        raise ValueError("evaluation bundle contains duplicate case_id")
    evaluations = {item.case_id: item for item in evaluation_items}
    observations: list[BenchmarkObservation] = []
    selected_ids: set[str] = set()
    completed = 0

    for execution in artifact.cases:
        case = cases.get(execution.case_id)
        if case is None:
            raise ValueError(f"run references unknown case {execution.case_id}")
        selected_ids.add(execution.case_id)
        if execution.status == "failed":
            observations.append(_failed_observation(case, execution))
            continue
        completed += 1
        if execution.evaluation_state == "automatic":
            observations.append(_automatic_observation(case, execution))
            continue
        evaluation = evaluations.get(execution.case_id)
        if evaluation is None:
            raise ValueError(
                f"missing evaluation for completed case {execution.case_id}"
            )
        observations.append(
            _observation_from_evaluation(case, execution, evaluation)
        )


    unexpected = sorted(set(evaluations) - selected_ids)
    if unexpected:
        raise ValueError(f"evaluation contains cases outside run: {unexpected}")

    metric_names = TRACK_METRICS.get(artifact.track)
    if metric_names is None:
        raise ValueError(f"unsupported evaluation track {artifact.track}")
    summary = aggregate(
        dataset,
        observations,
        artifact.benchmark_class,
        case_ids=selected_ids,
        metric_names=metric_names,
    )
    return {
        "schema_version": 1,
        "run_id": artifact.run_id,
        "suite_id": artifact.suite_id,
        "track": artifact.track,
        "subject": artifact.subject.model_dump(),
        "case_count": artifact.case_count,
        "completed_count": completed,
        "completion_rate": completed / artifact.case_count if artifact.case_count else 0.0,
        "evaluation": (
            {
                "evaluator_type": bundle.evaluator_type,
                "evaluator_id": bundle.evaluator_id,
                "evaluator_version": bundle.evaluator_version,
            }
            if bundle else {"evaluator_type": "automatic"}
        ),
        "aggregate": summary,
    }


def _locator_path(locator: str) -> str | None:
    value = locator.partition("#")[0].strip()
    if not value or " p." in value or " pp." in value:
        return None
    return value.replace("\\", "/").lstrip("./")


def _hit_matches_evidence(hit, evidence) -> bool:
    locator_path = _locator_path(evidence.locator)
    candidates = [
        hit.repository_path or "",
        hit.source_uri or "",
    ]
    if locator_path and any(
        candidate.replace("\\", "/").endswith(locator_path)
        for candidate in candidates
    ):
        return True

    # Atomic JSONL records preserve their exact source IDs in chunk text.
    # Match the identifier as a token-like literal, never a fuzzy substring.
    escaped = __import__("re").escape(evidence.source_id)
    return bool(__import__("re").search(
        rf'(?<![A-Za-z0-9_.-]){escaped}(?![A-Za-z0-9_.-])',
        hit.text or "",
    ))


def deterministic_retrieval_bundle(
    artifact: BenchmarkRunArtifact,
    dataset: GoldenDataset,
) -> EvaluationBundle:
    if artifact.track not in {"retrieval_only", "retrieval_plus_reranker"}:
        raise ValueError("deterministic retrieval evaluator requires retrieval track")
    cases = _case_lookup(dataset)
    evaluations: list[CaseEvaluation] = []
    for execution in artifact.cases:
        case = cases.get(execution.case_id)
        if case is None:
            raise ValueError(f"run references unknown case {execution.case_id}")
        relevant: list[RelevantResult] = []
        for hit in execution.hits:
            supported: set[str] = set()
            for evidence in case.expected_evidence:
                if _hit_matches_evidence(hit, evidence):
                    supported.update(evidence.supports_fact_ids)
            if supported:
                relevant.append(RelevantResult(
                    result_id=hit.result_id,
                    supports_fact_ids=sorted(supported),
                ))
        evaluations.append(CaseEvaluation(
            case_id=case.case_id,
            relevant_results=relevant,
        ))
    return EvaluationBundle(
        run_id=artifact.run_id,
        evaluator_type="deterministic",
        evaluator_id="source-identity-v1",
        evaluator_version="1",
        cases=evaluations,
    )
