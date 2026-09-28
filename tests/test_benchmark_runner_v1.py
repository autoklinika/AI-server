import json
from pathlib import Path

import httpx

from ai_bridge.benchmarks.contracts import GoldenCase
from ai_bridge.benchmarks.platform_client import PlatformBenchmarkClient
from ai_bridge.benchmarks.runner import (
    BenchmarkRunArtifact,
    BenchmarkSubject,
    CaseExecution,
    RetrievedHitArtifact,
    RouterDecision,
    dry_run,
    run_end_to_end_rag,
    run_fixed_evidence_llm,
    run_retrieval,
    run_router,
)


ROOT = Path(__file__).resolve().parents[1]
SUITES = ROOT / "benchmarks" / "automotive_v1" / "suites"


def _case(*, target="llm", source_id="FIX-1", locator="fixture.md"):
    return {
        "schema_version": 1,
        "case_id": "ERS-GOLD-TEST1",
        "targets": [target],
        "question": "What does the evidence say?",
        "query_variants": [],
        "context_turns": [],
        "category": "test",
        "difficulty": "easy",
        "language": "en",
        "split": "dev",
        "training_exclusion": True,

        "expected_facts": [{
            "fact_id": "f1", "statement": "The value is 42.", "required": True,
        }],
        "expected_evidence": [{
            "source_id": source_id,
            "locator": locator,
            "supports_fact_ids": ["f1"],
        }],
        "acceptable_answer": {
            "reference": "The value is 42.",
            "required_concepts": ["42"],
            "optional_concepts": [],
        },
        "forbidden_claims": [],
        "required_tools": ["knowledge.search"] if target != "router" else [],
        "expected_routing": {
            "primary": "knowledge_rag" if target != "router" else "reasoning",
            "requires_knowledge": target != "router",
            "requires_graph": False,
            "requires_vision": False,
            "expected_tools": ["knowledge.search"] if target != "router" else [],
        },
        "grounding": {
            "must_cite": target != "router",
            "minimum_source_coverage": 1.0 if target != "router" else 0.0,
            "fail_closed_if_missing": True,
        },
        "expected_confidence": {"grounded_min": 0.8, "ungrounded_max": 0.2},
        "provenance": {
            "source_repo": "test/repo",
            "source_ids": [source_id],
            "case_ids": [],
            "reuse_status": "test",
        },
        "tags": ["test"],
    }


def _dataset(tmp_path, case):
    path = tmp_path / "golden.jsonl"
    path.write_text(json.dumps(case) + "\n", encoding="utf-8")
    return path


def _health():
    return httpx.Response(200, json={
        "schema_version": 1,
        "status": "ready",
        "readiness": True,
        "components": {"resource_manager": {"status": "ready"}},
    })


def test_dry_run_never_calls_platform(tmp_path):
    dataset = _dataset(tmp_path, _case(target="retrieval_rag"))
    subject = BenchmarkSubject(
        subject_id="knowledge-hybrid",
        kind="knowledge-config",
        adapter="knowledge-api-v1",
    )
    artifact = dry_run(
        suite_path=SUITES / "retrieval_rag.json",
        dataset_path=dataset,
        track="retrieval_only",
        subject=subject,
        source_revisions={"ai_server_commit": "abc"},
    )
    assert artifact.mode == "dry-run"
    assert artifact.case_count == 1
    assert artifact.cases[0].status == "planned"
    assert artifact.cases[0].endpoint == "/api/v1/knowledge/search"


def test_fixed_evidence_runner_uses_platform_ai_background_priority(tmp_path):
    dataset = _dataset(tmp_path, _case())
    ers = tmp_path / "ers"
    ers.mkdir()
    (ers / "fixture.md").write_text("# Fact\nThe value is 42.\n", encoding="utf-8")
    seen = {}


    def handler(request):
        if request.url.path == "/api/v1/health":
            return _health()
        seen["path"] = request.url.path
        seen["body"] = json.loads(request.content)
        body = seen["body"]
        return httpx.Response(200, json={
            "schema_version": 1,
            "request_id": body["context"]["request_id"],
            "state": "completed",
            "content": json.dumps({
                "answer": "42 [FIX-1]",
                "cited_source_ids": ["FIX-1"],
                "insufficient_context": False,
            }),
            "finish_reason": "stop",
            "usage": {"input_tokens": 100, "output_tokens": 12},
            "execution": {
                "provider": "ollama-local",
                "model": "reasoning-main",
                "node": "test-node",
                "queue_wait_ms": 1.5,
                "duration_ms": 12.0,
            },
        })

    client = PlatformBenchmarkClient(
        "http://platform",
        transport=httpx.MockTransport(handler),
    )
    subject = BenchmarkSubject(
        subject_id="reasoning-main",
        kind="logical-llm",
        adapter="platform-ai-v1",
    )
    artifact = run_fixed_evidence_llm(
        client=client,
        suite_path=SUITES / "llm.json",
        dataset_path=dataset,
        subject=subject,
        ai_root=ROOT,
        ers_root=ers,
        source_revisions={"ai_server_commit": "abc", "ers_commit": "def"},
    )

    assert seen["path"] == "/api/v1/ai"
    assert seen["body"]["priority_class"] == "background"
    assert seen["body"]["capability"] == "structured-generation"
    assert "The value is 42." in seen["body"]["messages"][0]["content"]
    assert artifact.cases[0].evaluation_state == "pending_semantic"
    assert artifact.cases[0].cited_source_ids == ["FIX-1"]


def test_retrieval_runner_uses_stable_knowledge_api(tmp_path):
    dataset = _dataset(tmp_path, _case(target="retrieval_rag"))
    seen = {}

    def handler(request):
        if request.url.path == "/api/v1/health":
            return _health()
        seen["path"] = request.url.path
        seen["body"] = json.loads(request.content)
        rid = request.headers["x-request-id"]
        return httpx.Response(200, json={
            "schema_version": 1,
            "request_id": rid,
            "mode": "hybrid",
            "backend": "composite",
            "duration_ms": 4.2,
            "results": [{
                "result_id": "chunk-1",
                "text": "The value is 42.",
                "score": 0.9,
                "source": {"type": "documentation", "uri": "repo://fixture.md", "title": "Fixture"},
                "metadata": {"source_id": "FIX-1", "repository_path": "fixture.md"},
            }],
        })

    client = PlatformBenchmarkClient("http://platform", transport=httpx.MockTransport(handler))
    subject = BenchmarkSubject(
        subject_id="knowledge-hybrid",
        kind="knowledge-config",
        adapter="knowledge-api-v1",
    )

    artifact = run_retrieval(
        client=client,
        suite_path=SUITES / "retrieval_rag.json",
        dataset_path=dataset,
        subject=subject,
        track="retrieval_only",
        source_revisions={"ai_server_commit": "abc"},
    )
    assert seen["path"] == "/api/v1/knowledge/search"
    assert seen["body"]["mode"] == "hybrid"
    assert seen["body"]["rerank"] is False
    assert artifact.cases[0].evaluation_state == "pending_relevance"
    assert artifact.cases[0].hits[0].source_id == "FIX-1"
    assert artifact.cases[0].hits[0].text == "The value is 42."


def test_rag_runner_uses_grounded_knowledge_ask_background(tmp_path):
    dataset = _dataset(tmp_path, _case(target="retrieval_rag"))
    seen = {}

    def handler(request):
        if request.url.path == "/api/v1/health":
            return _health()
        seen["path"] = request.url.path
        seen["body"] = json.loads(request.content)
        rid = request.headers["x-request-id"]
        return httpx.Response(200, json={
            "schema_version": 1,
            "request_id": rid,
            "answer": "The value is 42.",
            "claims": [{"text": "42", "source_refs": ["S1"]}],
            "insufficient_context": False,
            "citations": [{
                "ref": "S1",
                "source": {"type": "documentation", "uri": "repo://fixture.md", "title": "Fixture"},
                "document_id": "doc-1", "chunk_id": "chunk-1",
            }],
            "retrieval": {"mode": "hybrid", "backend": "composite", "result_count": 1},
            "execution": {"model": "reasoning-main", "queue_wait_ms": 2.0, "duration_ms": 15.0},
        })


    client = PlatformBenchmarkClient("http://platform", transport=httpx.MockTransport(handler))
    subject = BenchmarkSubject(
        subject_id="rag-hybrid",
        kind="knowledge-config",
        adapter="knowledge-api-v1",
    )
    artifact = run_end_to_end_rag(
        client=client,
        suite_path=SUITES / "retrieval_rag.json",
        dataset_path=dataset,
        subject=subject,
        source_revisions={"ai_server_commit": "abc"},
    )
    assert seen["path"] == "/api/v1/knowledge/ask"
    assert seen["body"]["priority_class"] == "background"
    assert seen["body"]["require_grounding_signal"] is True
    assert artifact.cases[0].evaluation_state == "pending_semantic"
    assert "doc-1" in artifact.cases[0].cited_source_ids


def test_router_adapter_is_separate_from_large_llm(tmp_path):
    dataset = _dataset(tmp_path, _case(target="router"))

    class FakeRouter:
        def decide(self, case):
            assert isinstance(case, GoldenCase)
            return RouterDecision(route="reasoning", selected_tools=[], latency_ms=2.5)

    subject = BenchmarkSubject(
        subject_id="fake-router",
        kind="router-checkpoint",
        adapter="router-adapter-v1",
    )
    artifact = run_router(
        adapter=FakeRouter(),
        suite_path=SUITES / "router.json",
        dataset_path=dataset,
        subject=subject,
        track="routing_zero_shot",
        source_revisions={"ai_server_commit": "abc"},
    )
    assert artifact.cases[0].evaluation_state == "automatic"
    assert artifact.cases[0].route == "reasoning"
    assert artifact.cases[0].latency_ms == 2.5


def test_missing_fixed_evidence_aborts_before_platform_call(tmp_path):
    dataset = _dataset(tmp_path, _case(locator="missing.md"))
    ers = tmp_path / "ers"
    ers.mkdir()
    calls = []

    def handler(request):
        calls.append(request.url.path)
        return _health()

    client = PlatformBenchmarkClient("http://platform", transport=httpx.MockTransport(handler))
    subject = BenchmarkSubject(
        subject_id="reasoning-main",
        kind="logical-llm",
        adapter="platform-ai-v1",
    )
    import pytest
    with pytest.raises(ValueError, match="cannot resolve fixed evidence"):
        run_fixed_evidence_llm(
            client=client,
            suite_path=SUITES / "llm.json",
            dataset_path=dataset,
            subject=subject,
            ai_root=ROOT,
            ers_root=ers,
            source_revisions={"ai_server_commit": "abc"},
        )
    assert calls == []


def test_degraded_resource_manager_aborts_before_retrieval(tmp_path):
    dataset = _dataset(tmp_path, _case(target="retrieval_rag"))
    calls = []

    def handler(request):
        calls.append(request.url.path)
        return httpx.Response(200, json={
            "schema_version": 1,
            "status": "degraded",
            "readiness": False,
            "components": {"resource_manager": {"status": "blocked"}},
        })

    client = PlatformBenchmarkClient("http://platform", transport=httpx.MockTransport(handler))
    subject = BenchmarkSubject(
        subject_id="knowledge-hybrid",
        kind="knowledge-config",
        adapter="knowledge-api-v1",
    )
    import pytest
    with pytest.raises(RuntimeError, match="not benchmark-ready"):
        run_retrieval(
            client=client,
            suite_path=SUITES / "retrieval_rag.json",
            dataset_path=dataset,
            subject=subject,
            track="retrieval_only",
            source_revisions={"ai_server_commit": "abc"},
        )
    assert calls == ["/api/v1/health"]


def test_finalize_router_run_is_automatic_and_version_locked(tmp_path):
    from ai_bridge.benchmarks.contracts import GoldenDataset
    from ai_bridge.benchmarks.evaluation import finalize_run

    dataset_path = _dataset(tmp_path, _case(target="router"))
    dataset = GoldenDataset.load_jsonl(dataset_path)

    class FakeRouter:
        def decide(self, case):
            return RouterDecision(route="reasoning", selected_tools=[], latency_ms=2.0)

    artifact = run_router(
        adapter=FakeRouter(),
        suite_path=SUITES / "router.json",
        dataset_path=dataset_path,
        subject=BenchmarkSubject(
            subject_id="fake-router",
            kind="router-checkpoint",
            adapter="router-adapter-v1",
        ),
        track="routing_zero_shot",
        source_revisions={"ai_server_commit": "abc"},
    )
    result = finalize_run(
        artifact, dataset, None, dataset_path=dataset_path
    )
    assert result["evaluation"]["evaluator_type"] == "automatic"
    assert result["aggregate"]["metrics"]["route_accuracy"] == 1.0

    dataset_path.write_text(dataset_path.read_text() + "\n", encoding="utf-8")
    import pytest
    with pytest.raises(ValueError, match="dataset SHA-256 mismatch"):
        finalize_run(
            artifact,
            GoldenDataset.load_jsonl(dataset_path),
            None,
            dataset_path=dataset_path,
        )


def test_finalize_semantic_run_requires_explicit_evaluation(tmp_path):
    from ai_bridge.benchmarks.contracts import GoldenDataset
    from ai_bridge.benchmarks.evaluation import finalize_run

    dataset_path = _dataset(tmp_path, _case())
    dataset = GoldenDataset.load_jsonl(dataset_path)
    artifact = BenchmarkRunArtifact(
        run_id="run_semantic",
        suite_id="automotive-reasoning",
        benchmark_class="llm",
        track="reasoning_fixed_evidence",
        subject=BenchmarkSubject(
            subject_id="reasoning-main",
            kind="logical-llm",
            adapter="platform-ai-v1",
        ),
        mode="recorded",
        dataset_sha256=__import__("hashlib").sha256(
            dataset_path.read_bytes()
        ).hexdigest(),
        source_revisions={"ai_server_commit": "abc"},
        case_count=1,
        cases=[CaseExecution(
            case_id="ERS-GOLD-TEST1",
            request_id="req",
            endpoint="/api/v1/ai",
            status="completed",
            evaluation_state="pending_semantic",
            answer="42",
        )],
    )
    import pytest
    with pytest.raises(ValueError, match="missing evaluation"):
        finalize_run(artifact, dataset, None, dataset_path=dataset_path)


def test_deterministic_retrieval_matches_repository_locator(tmp_path):
    from ai_bridge.benchmarks.contracts import GoldenDataset
    from ai_bridge.benchmarks.evaluation import (
        deterministic_retrieval_bundle,
        finalize_run,
    )

    case = _case(target="retrieval_rag", locator="docs/fixture.md")
    dataset_path = _dataset(tmp_path, case)
    dataset = GoldenDataset.load_jsonl(dataset_path)
    artifact = BenchmarkRunArtifact(
        run_id="run_retrieval_eval",
        suite_id="rag-knowledge",
        benchmark_class="retrieval_rag",
        track="retrieval_only",
        subject=BenchmarkSubject(
            subject_id="knowledge-hybrid",
            kind="knowledge-config",
            adapter="knowledge-api-v1",
        ),
        mode="recorded",
        dataset_sha256=__import__("hashlib").sha256(
            dataset_path.read_bytes()
        ).hexdigest(),
        source_revisions={"ai_server_commit": "abc"},
        case_count=1,
        cases=[CaseExecution(
            case_id="ERS-GOLD-TEST1",
            request_id="req",
            endpoint="/api/v1/knowledge/search",
            status="completed",
            evaluation_state="pending_relevance",
            hits=[RetrievedHitArtifact(
                rank=1,
                result_id="hit-1",
                score=0.9,
                source_uri="github://test/repo/docs/fixture.md",
                source_title="Fixture",
                source_id="ksrc_internal",
                repository_path=None,
                text="The value is 42.",
            )],
        )],
    )
    bundle = deterministic_retrieval_bundle(artifact, dataset)
    result = finalize_run(
        artifact, dataset, bundle, dataset_path=dataset_path
    )
    metrics = result["aggregate"]["metrics"]
    assert metrics["evidence_recall_at_1"] == 1.0
    assert metrics["mrr"] == 1.0
    assert result["evaluation"]["evaluator_id"] == "source-identity-v1"


def test_retrieval_plus_reranker_sets_stable_api_flag(tmp_path):
    dataset = _dataset(tmp_path, _case(target="retrieval_rag"))
    seen = {}

    def handler(request):
        if request.url.path == "/api/v1/health":
            return _health()
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={
            "schema_version": 1,
            "request_id": request.headers["x-request-id"],
            "mode": "hybrid",
            "backend": "composite",
            "duration_ms": 1.0,
            "results": [],
        })

    artifact = run_retrieval(
        client=PlatformBenchmarkClient(
            "http://platform", transport=httpx.MockTransport(handler)
        ),
        suite_path=SUITES / "retrieval_rag.json",
        dataset_path=dataset,
        subject=BenchmarkSubject(
            subject_id="knowledge-reranked",
            kind="knowledge-config",
            adapter="knowledge-api-v1",
        ),
        track="retrieval_plus_reranker",
        source_revisions={"ai_server_commit": "abc"},
    )
    assert artifact.track == "retrieval_plus_reranker"
    assert seen["body"]["rerank"] is True
