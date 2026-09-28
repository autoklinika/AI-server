"""Benchmark execution engine over stable AI Platform APIs."""
from __future__ import annotations

import hashlib
import json
import time
import uuid
from pathlib import Path
from typing import Literal, Protocol

from pydantic import Field

from .contracts import GoldenCase, GoldenDataset, StrictModel, SuiteManifest
from .evidence import render_fixed_evidence, resolve_evidence
from .platform_client import PlatformBenchmarkClient
from .resources import ResourceSampler, SystemResourceUsage


class BenchmarkSubject(StrictModel):
    subject_id: str
    kind: Literal["logical-llm", "knowledge-config", "router-checkpoint"]
    adapter: Literal["platform-ai-v1", "knowledge-api-v1", "router-adapter-v1"]
    metadata: dict = Field(default_factory=dict)


class RetrievedHitArtifact(StrictModel):
    rank: int = Field(ge=1)
    result_id: str
    score: float
    source_uri: str
    source_title: str | None = None
    source_id: str | None = None
    repository_path: str | None = None
    page: int | None = None
    section: str | None = None
    text: str


class CaseExecution(StrictModel):
    case_id: str
    request_id: str
    endpoint: str
    status: Literal["planned", "completed", "failed"]
    evaluation_state: Literal[
        "not_started", "pending_semantic", "pending_relevance", "automatic"
    ]
    answer: str | None = None
    cited_source_ids: list[str] = Field(default_factory=list)
    citation_count: int | None = Field(default=None, ge=0)
    insufficient_context: bool | None = None
    hits: list[RetrievedHitArtifact] = Field(default_factory=list)
    route: str | None = None
    selected_tools: list[str] = Field(default_factory=list)
    latency_ms: float | None = Field(default=None, ge=0)
    peak_ram_bytes: int | None = Field(default=None, ge=0)
    queue_wait_ms: float | None = Field(default=None, ge=0)
    usage: dict = Field(default_factory=dict)
    throughput_tps: float | None = Field(default=None, ge=0)
    resource_usage: SystemResourceUsage | None = None
    error_code: str | None = None


class BenchmarkRunArtifact(StrictModel):
    schema_version: Literal[1] = 1
    run_id: str
    suite_id: str
    benchmark_class: str
    track: str
    subject: BenchmarkSubject
    mode: Literal["dry-run", "live", "recorded"]
    dataset_sha256: str
    source_revisions: dict[str, str | None]
    case_count: int
    cases: list[CaseExecution]


class RouterDecision(StrictModel):
    route: str
    selected_tools: list[str] = Field(default_factory=list)
    latency_ms: float | None = Field(default=None, ge=0)
    peak_ram_bytes: int | None = Field(default=None, ge=0)


class RouterAdapter(Protocol):
    def decide(self, case: GoldenCase) -> RouterDecision: ...


_FIXED_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "answer": {"type": "string"},
        "cited_source_ids": {"type": "array", "items": {"type": "string"}},
        "insufficient_context": {"type": "boolean"},
    },
    "required": ["answer", "cited_source_ids", "insufficient_context"],
    "additionalProperties": False,
}


def _dataset_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sampled(call):
    sampler = ResourceSampler().start()
    try:
        value = call()
    except Exception:
        sampler.stop()
        raise
    return value, sampler.stop()


def _throughput_tps(usage: dict | None, duration_ms: float | None) -> float | None:
    if not usage or not duration_ms or duration_ms <= 0:
        return None
    output_tokens = usage.get("output_tokens")
    if type(output_tokens) is not int or output_tokens < 0:
        return None
    return output_tokens / (duration_ms / 1000.0)


def _request_id(case: GoldenCase, run_id: str) -> str:
    return f"bench_{run_id[-12:]}_{case.case_id.lower().replace('-', '_')}"[:127]


def _selected_cases(
    dataset: GoldenDataset,
    suite: SuiteManifest,
    splits: set[str] | None,
    case_ids: set[str] | None = None,
) -> list[GoldenCase]:
    selected = [
        case for case in dataset.cases
        if suite.benchmark_class in case.targets
        and (not splits or case.split in splits)
        and (not case_ids or case.case_id in case_ids)
    ]
    if case_ids:
        found = {case.case_id for case in selected}
        missing = sorted(case_ids - found)
        if missing:
            raise ValueError(f"selected case ids not in suite/split: {missing}")
    return selected


def _base_artifact(
    *,
    suite: SuiteManifest,
    track: str,
    subject: BenchmarkSubject,
    mode: str,
    dataset_path: Path,
    source_revisions: dict[str, str | None],
    cases: list[CaseExecution],
    run_id: str,
) -> BenchmarkRunArtifact:
    return BenchmarkRunArtifact(
        run_id=run_id,
        suite_id=suite.suite_id,
        benchmark_class=suite.benchmark_class,
        track=track,
        subject=subject,
        mode=mode,
        dataset_sha256=_dataset_hash(dataset_path),
        source_revisions=source_revisions,
        case_count=len(cases),
        cases=cases,
    )


def dry_run(
    *,
    suite_path: Path,
    dataset_path: Path,
    track: str,
    subject: BenchmarkSubject,
    source_revisions: dict[str, str | None],
    splits: set[str] | None = None,
    case_ids: set[str] | None = None,
) -> BenchmarkRunArtifact:
    suite = SuiteManifest.load(suite_path)
    if track not in suite.tracks:
        raise ValueError(f"unsupported track {track!r}")
    dataset = GoldenDataset.load_jsonl(dataset_path)
    cases = _selected_cases(dataset, suite, splits, case_ids)
    run_id = "dry_" + uuid.uuid4().hex[:20]

    endpoint = {
        "reasoning_fixed_evidence": "/api/v1/ai",
        "closed_book_diagnostic": "/api/v1/ai",
        "tool_use_multiturn": "/api/v1/ai",
        "retrieval_only": "/api/v1/knowledge/search",
        "retrieval_plus_reranker": "/api/v1/knowledge/search",
        "end_to_end_rag": "/api/v1/knowledge/ask",
        "routing_zero_shot": "router-adapter-v1",
        "routing_calibrated": "router-adapter-v1",
        "routing_finetuned": "router-adapter-v1",
    }[track]
    planned = [
        CaseExecution(
            case_id=case.case_id,
            request_id=_request_id(case, run_id),
            endpoint=endpoint,
            status="planned",
            evaluation_state="not_started",
        )
        for case in cases
    ]
    return _base_artifact(
        suite=suite,
        track=track,
        subject=subject,
        mode="dry-run",
        dataset_path=dataset_path,
        source_revisions=source_revisions,
        cases=planned,
        run_id=run_id,
    )


class _FixedAnswer(StrictModel):
    answer: str
    cited_source_ids: list[str]
    insufficient_context: bool


def _failure(case: GoldenCase, run_id: str, endpoint: str, exc: Exception) -> CaseExecution:
    return CaseExecution(
        case_id=case.case_id,
        request_id=_request_id(case, run_id),
        endpoint=endpoint,
        status="failed",
        evaluation_state="not_started",
        error_code=type(exc).__name__,
    )


def run_fixed_evidence_llm(
    *,
    client: PlatformBenchmarkClient,
    suite_path: Path,
    dataset_path: Path,
    subject: BenchmarkSubject,
    ai_root: Path,
    ers_root: Path,
    source_revisions: dict[str, str | None],
    model: str = "reasoning-main",
    splits: set[str] | None = None,
    case_ids: set[str] | None = None,
) -> BenchmarkRunArtifact:
    suite = SuiteManifest.load(suite_path)
    if suite.benchmark_class != "llm" or "reasoning_fixed_evidence" not in suite.tracks:
        raise ValueError("suite does not support fixed-evidence LLM execution")
    if subject.adapter != "platform-ai-v1":
        raise ValueError("fixed-evidence LLM requires platform-ai-v1 adapter")
    dataset = GoldenDataset.load_jsonl(dataset_path)
    selected = _selected_cases(dataset, suite, splits, case_ids)
    evidence_by_case = {
        case.case_id: resolve_evidence(case, ai_root=ai_root, ers_root=ers_root)
        for case in selected
    }
    client.assert_ready()
    run_id = "run_" + uuid.uuid4().hex[:20]
    results: list[CaseExecution] = []

    for case in selected:
        request_id = _request_id(case, run_id)
        try:
            response, resources = _sampled(lambda: client.ai_structured(
                request_id=request_id,
                message=render_fixed_evidence(case, evidence_by_case[case.case_id]),
                response_schema=_FIXED_RESPONSE_SCHEMA,
                model=model,
            ))
            parsed = _FixedAnswer.model_validate_json(response.content)
            results.append(CaseExecution(
                case_id=case.case_id,
                request_id=request_id,
                endpoint="/api/v1/ai",
                status="completed",
                evaluation_state="pending_semantic",
                answer=parsed.answer,
                cited_source_ids=parsed.cited_source_ids,
                citation_count=len(parsed.cited_source_ids),
                insufficient_context=parsed.insufficient_context,
                latency_ms=response.execution.duration_ms,
                queue_wait_ms=response.execution.queue_wait_ms,
                usage=response.usage,
                throughput_tps=_throughput_tps(
                    response.usage, response.execution.duration_ms
                ),
                resource_usage=resources,
            ))
        except Exception as exc:
            results.append(_failure(case, run_id, "/api/v1/ai", exc))
    return _base_artifact(
        suite=suite,
        track="reasoning_fixed_evidence",
        subject=subject,
        mode="live",
        dataset_path=dataset_path,
        source_revisions=source_revisions,
        cases=results,
        run_id=run_id,
    )


def _hit_artifact(rank: int, hit) -> RetrievedHitArtifact:
    metadata = hit.metadata
    return RetrievedHitArtifact(
        rank=rank,
        result_id=hit.result_id,
        score=hit.score,
        source_uri=hit.source.uri,
        source_title=hit.source.title,
        source_id=metadata.get("source_id"),
        repository_path=metadata.get("repository_path"),
        page=metadata.get("page"),
        section=metadata.get("section"),
        text=hit.text,
    )


def run_retrieval(
    *,
    client: PlatformBenchmarkClient,
    suite_path: Path,
    dataset_path: Path,
    subject: BenchmarkSubject,
    track: Literal["retrieval_only", "retrieval_plus_reranker"],
    source_revisions: dict[str, str | None],
    mode: str = "hybrid",
    limit: int = 10,
    splits: set[str] | None = None,
    case_ids: set[str] | None = None,
) -> BenchmarkRunArtifact:
    suite = SuiteManifest.load(suite_path)
    if suite.benchmark_class != "retrieval_rag" or track not in suite.tracks:
        raise ValueError("suite does not support requested retrieval track")
    if subject.adapter != "knowledge-api-v1":
        raise ValueError("retrieval requires knowledge-api-v1 adapter")

    dataset = GoldenDataset.load_jsonl(dataset_path)
    selected = _selected_cases(dataset, suite, splits, case_ids)
    client.assert_ready()
    run_id = "run_" + uuid.uuid4().hex[:20]
    results: list[CaseExecution] = []
    for case in selected:
        request_id = _request_id(case, run_id)
        try:
            response, resources = _sampled(lambda: client.knowledge_search(
                request_id=request_id,
                query=case.question,
                mode=mode,
                limit=limit,
                rerank=(track == "retrieval_plus_reranker"),
            ))
            results.append(CaseExecution(
                case_id=case.case_id,
                request_id=request_id,
                endpoint="/api/v1/knowledge/search",
                status="completed",
                evaluation_state="pending_relevance",
                hits=[
                    _hit_artifact(rank, hit)
                    for rank, hit in enumerate(response.results, 1)
                ],
                latency_ms=response.duration_ms,
                resource_usage=resources,
            ))
        except Exception as exc:
            results.append(_failure(
                case, run_id, "/api/v1/knowledge/search", exc
            ))
    return _base_artifact(
        suite=suite,
        track=track,
        subject=subject,
        mode="live",
        dataset_path=dataset_path,
        source_revisions=source_revisions,
        cases=results,
        run_id=run_id,
    )


def _citation_ids(citations: list[dict]) -> list[str]:
    values: list[str] = []
    for item in citations:
        for candidate in (
            item.get("document_id"),
            item.get("chunk_id"),
            (item.get("source") or {}).get("uri"),
        ):
            if isinstance(candidate, str) and candidate and candidate not in values:
                values.append(candidate)
    return values


def run_end_to_end_rag(
    *,
    client: PlatformBenchmarkClient,
    suite_path: Path,
    dataset_path: Path,
    subject: BenchmarkSubject,
    source_revisions: dict[str, str | None],
    mode: str = "hybrid",
    limit: int = 8,
    splits: set[str] | None = None,
    case_ids: set[str] | None = None,
) -> BenchmarkRunArtifact:
    suite = SuiteManifest.load(suite_path)
    if suite.benchmark_class != "retrieval_rag" or "end_to_end_rag" not in suite.tracks:
        raise ValueError("suite does not support end-to-end RAG")
    if subject.adapter != "knowledge-api-v1":
        raise ValueError("RAG requires knowledge-api-v1 adapter")
    dataset = GoldenDataset.load_jsonl(dataset_path)
    selected = _selected_cases(dataset, suite, splits, case_ids)
    client.assert_ready()
    run_id = "run_" + uuid.uuid4().hex[:20]
    results: list[CaseExecution] = []

    for case in selected:
        request_id = _request_id(case, run_id)
        try:
            started = time.perf_counter()
            response, resources = _sampled(lambda: client.knowledge_ask(
                request_id=request_id,
                query=case.question,
                mode=mode,
                limit=limit,
            ))
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            execution = response.execution or {}
            results.append(CaseExecution(
                case_id=case.case_id,
                request_id=request_id,
                endpoint="/api/v1/knowledge/ask",
                status="completed",
                evaluation_state="pending_semantic",
                answer=response.answer,
                cited_source_ids=_citation_ids(response.citations),
                citation_count=len(response.citations),
                insufficient_context=response.insufficient_context,
                latency_ms=float(execution.get("duration_ms", elapsed_ms)),
                queue_wait_ms=execution.get("queue_wait_ms"),
                usage=response.usage or {},
                throughput_tps=_throughput_tps(
                    response.usage,
                    float(execution.get("duration_ms", elapsed_ms)),
                ),
                resource_usage=resources,
            ))
        except Exception as exc:
            results.append(_failure(case, run_id, "/api/v1/knowledge/ask", exc))
    return _base_artifact(
        suite=suite,
        track="end_to_end_rag",
        subject=subject,
        mode="live",
        dataset_path=dataset_path,
        source_revisions=source_revisions,
        cases=results,
        run_id=run_id,
    )


def run_router(
    *,
    adapter: RouterAdapter,
    suite_path: Path,
    dataset_path: Path,
    subject: BenchmarkSubject,
    track: str,
    source_revisions: dict[str, str | None],
    splits: set[str] | None = None,
    case_ids: set[str] | None = None,
) -> BenchmarkRunArtifact:

    suite = SuiteManifest.load(suite_path)
    if suite.benchmark_class != "router" or track not in suite.tracks:
        raise ValueError("suite does not support requested router track")
    if subject.adapter != "router-adapter-v1":
        raise ValueError("router benchmark requires router-adapter-v1")
    dataset = GoldenDataset.load_jsonl(dataset_path)
    selected = _selected_cases(dataset, suite, splits, case_ids)
    run_id = "run_" + uuid.uuid4().hex[:20]
    results: list[CaseExecution] = []
    for case in selected:
        request_id = _request_id(case, run_id)
        try:
            decision, resources = _sampled(lambda: adapter.decide(case))
            results.append(CaseExecution(
                case_id=case.case_id,
                request_id=request_id,
                endpoint="router-adapter-v1",
                status="completed",
                evaluation_state="automatic",
                route=decision.route,
                selected_tools=decision.selected_tools,
                latency_ms=decision.latency_ms,
                peak_ram_bytes=decision.peak_ram_bytes,
                resource_usage=resources,
            ))
        except Exception as exc:
            results.append(_failure(case, run_id, "router-adapter-v1", exc))
    return _base_artifact(
        suite=suite,
        track=track,
        subject=subject,
        mode="live",
        dataset_path=dataset_path,
        source_revisions=source_revisions,
        cases=results,
        run_id=run_id,
    )


def write_artifact(path: Path, artifact: BenchmarkRunArtifact) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = artifact.model_dump_json(indent=2) + "\n"
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(payload, encoding="utf-8")
    temporary.replace(path)
