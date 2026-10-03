"""CLI for benchmark dataset validation and reproducible run planning."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from .contracts import GoldenDataset, SuiteManifest
from .coverage import CoveragePolicy, evaluate_coverage
from .evaluation import (
    EvaluationBundle,
    deterministic_retrieval_bundle,
    finalize_run,
)
from .platform_client import PlatformBenchmarkClient
from .provenance import validate_ers_provenance
from .router_adapters import (
    Gliner2RouterAdapter,
    MajorityKnowledgeRouterAdapter,
    OllamaSystemOneRouterAdapter,
    RulesV1RouterAdapter,
)
from .run_manifest import build_run_plan, git_is_clean, git_revision
from .runner import (
    BenchmarkSubject,
    dry_run,
    run_end_to_end_rag,
    run_fixed_evidence_llm,
    run_retrieval,
    run_router,
    write_artifact,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ai-benchmark")
    sub = parser.add_subparsers(dest="command", required=True)

    validate = sub.add_parser("validate")
    validate.add_argument("--dataset", type=Path, required=True)
    validate.add_argument("--suite", action="append", type=Path, default=[])
    validate.add_argument("--ers-root", type=Path)
    validate.add_argument("--coverage-policy", type=Path)

    plan = sub.add_parser("plan")
    plan.add_argument("--suite", type=Path, required=True)
    plan.add_argument("--track", required=True)
    plan.add_argument("--dataset", type=Path, required=True)
    plan.add_argument("--ai-root", type=Path, required=True)
    plan.add_argument("--ers-root", type=Path)
    plan.add_argument("--output", type=Path)

    run = sub.add_parser("run")
    run.add_argument("--suite", type=Path, required=True)
    run.add_argument("--track", required=True)
    run.add_argument("--dataset", type=Path, required=True)
    run.add_argument("--subject-id", required=True)
    run.add_argument("--subject-kind", choices=[
        "logical-llm", "knowledge-config", "router-checkpoint"
    ], required=True)
    run.add_argument("--adapter", choices=[
        "platform-ai-v1", "knowledge-api-v1", "router-adapter-v1"
    ], required=True)
    run.add_argument("--mode", choices=["dry-run", "live"], default="dry-run")
    run.add_argument("--ai-root", type=Path, required=True)
    run.add_argument("--ers-root", type=Path)
    run.add_argument("--split", action="append", choices=["dev", "holdout", "challenge"])
    run.add_argument("--case-id", action="append")
    run.add_argument("--model", default="reasoning-main")
    run.add_argument("--model-num-ctx", type=int, default=65536)
    run.add_argument("--model-num-gpu", type=int, default=99)
    run.add_argument("--platform-url", default=os.getenv(
        "AI_PLATFORM_URL", "http://127.0.0.1:11435"
    ))
    run.add_argument("--knowledge-mode", choices=[
        "exact", "keyword", "semantic", "hybrid", "auto"
    ], default="hybrid")
    run.add_argument("--limit", type=int, default=10)
    run.add_argument(
        "--router-implementation",
        choices=[
            "majority-knowledge-v1", "rules-v1", "gliner2", "ollama-systemone"
        ],
    )
    run.add_argument("--router-checkpoint")
    run.add_argument("--router-url", default="http://127.0.0.1:11434")
    run.add_argument("--router-revision")
    run.add_argument("--router-threshold", type=float, default=0.5)
    run.add_argument("--allow-dirty", action="store_true")
    run.add_argument("--router-head-mode", choices=["joint", "separate"], default="joint")
    run.add_argument("--output", type=Path)

    evaluate = sub.add_parser("evaluate")
    evaluate.add_argument("--run", type=Path, required=True)
    evaluate.add_argument("--dataset", type=Path, required=True)
    evaluate.add_argument("--evaluation", type=Path)
    evaluate.add_argument("--deterministic-retrieval", action="store_true")
    evaluate.add_argument("--output", type=Path)
    return parser


def main() -> None:
    args = _parser().parse_args()
    if args.command == "evaluate":
        from .runner import BenchmarkRunArtifact

        artifact = BenchmarkRunArtifact.model_validate_json(
            args.run.read_text(encoding="utf-8")
        )
        dataset = GoldenDataset.load_jsonl(args.dataset)
        if args.evaluation and args.deterministic_retrieval:
            raise SystemExit(
                "choose either --evaluation or --deterministic-retrieval"
            )
        bundle = (
            EvaluationBundle.model_validate_json(
                args.evaluation.read_text(encoding="utf-8")
            )
            if args.evaluation else None
        )
        if args.deterministic_retrieval:
            bundle = deterministic_retrieval_bundle(artifact, dataset)
        result = finalize_run(
            artifact, dataset, bundle, dataset_path=args.dataset
        )
        encoded = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(encoded, encoding="utf-8")
        print(encoded, end="")
        return

    if args.command == "validate":
        dataset = GoldenDataset.load_jsonl(args.dataset)
        suites = [SuiteManifest.load(path).model_dump() for path in args.suite]
        provenance = validate_ers_provenance(dataset, args.ers_root) if args.ers_root else None
        coverage = (
            evaluate_coverage(dataset, CoveragePolicy.load(args.coverage_policy))
            if args.coverage_policy else None
        )
        status = "fail" if coverage and coverage["status"] == "fail" else "pass"
        print(json.dumps({
            "status": status,
            "dataset": dataset.summary(),
            "suites": suites,
            "provenance": provenance,
            "coverage": coverage,
        }, ensure_ascii=False, indent=2))
        if status != "pass":
            raise SystemExit(2)
        return

    if args.command == "run":
        suite = SuiteManifest.load(args.suite)
        splits = set(args.split or ())
        case_ids = set(args.case_id or ())
        if args.mode == "live" and not (splits or case_ids):
            raise SystemExit("live benchmark requires --split or --case-id")
        if args.mode == "live" and args.output is None:
            raise SystemExit("live benchmark requires --output")
        if args.mode == "live" and not args.allow_dirty:
            dirty_roots = [root for root in (args.ai_root, args.ers_root)
                           if root is not None and not git_is_clean(root)]
            if dirty_roots:
                joined = ", ".join(str(root) for root in dirty_roots)
                raise SystemExit(
                    "official live benchmark requires clean git worktrees: "
                    + joined
                )

        metadata = {}
        if args.adapter == "platform-ai-v1":
            metadata = {
                "model": args.model,
                "runtime_profile": {
                    "num_ctx": args.model_num_ctx,
                    "num_gpu": args.model_num_gpu,
                },
            }
        elif args.adapter == "knowledge-api-v1":
            metadata = {"knowledge_mode": args.knowledge_mode, "limit": args.limit}
        elif args.adapter == "router-adapter-v1" and args.router_implementation:
            metadata = {"router_implementation": args.router_implementation}
            if args.router_checkpoint:
                metadata["checkpoint"] = args.router_checkpoint
                metadata["revision"] = args.router_revision
                metadata["threshold"] = args.router_threshold
                metadata["head_mode"] = args.router_head_mode
            if args.allow_dirty:
                metadata["exploratory_dirty_worktree"] = True
        subject = BenchmarkSubject(
            subject_id=args.subject_id,
            kind=args.subject_kind,
            adapter=args.adapter,
            metadata=metadata,
        )
        revisions = {"ai_server_commit": git_revision(args.ai_root)}
        if args.ers_root:
            revisions["ers_commit"] = git_revision(args.ers_root)

        if args.mode == "dry-run":
            artifact = dry_run(
                suite_path=args.suite,
                dataset_path=args.dataset,
                track=args.track,
                subject=subject,
                source_revisions=revisions,
                splits=splits or None,
                case_ids=case_ids or None,
            )
        else:
            if suite.benchmark_class == "router":
                if args.adapter != "router-adapter-v1":
                    raise SystemExit("router live run requires router-adapter-v1")
                if args.router_implementation == "gliner2":
                    if not args.router_checkpoint:
                        raise SystemExit(
                            "GLiNER2 run requires --router-checkpoint"
                        )
                    if not args.router_revision:
                        raise SystemExit(
                            "GLiNER2 live run requires --router-revision"
                        )
                    router_adapter = Gliner2RouterAdapter(
                        args.router_checkpoint,
                        revision=args.router_revision,
                        threshold=args.router_threshold,
                        head_mode=args.router_head_mode,
                    )
                    subject.metadata["runtime"] = router_adapter.runtime_metadata()
                elif args.router_implementation == "ollama-systemone":
                    if not args.router_checkpoint:
                        raise SystemExit(
                            "System One run requires --router-checkpoint model name"
                        )
                    router_adapter = OllamaSystemOneRouterAdapter(
                        args.router_checkpoint,
                        base_url=args.router_url,
                        tool_threshold=args.router_threshold,
                    )
                    subject.metadata["runtime"] = router_adapter.runtime_metadata()
                else:
                    adapters = {
                        "majority-knowledge-v1": MajorityKnowledgeRouterAdapter,
                        "rules-v1": RulesV1RouterAdapter,
                    }
                    adapter_factory = adapters.get(args.router_implementation)
                    if adapter_factory is None:
                        raise SystemExit(
                            "router live run requires --router-implementation"
                        )
                    router_adapter = adapter_factory()
                artifact = run_router(
                    adapter=router_adapter,
                    suite_path=args.suite,
                    dataset_path=args.dataset,
                    subject=subject,
                    track=args.track,
                    source_revisions=revisions,
                    splits=splits or None,
                    case_ids=case_ids or None,
                )
            else:
                token = os.getenv("AI_PLATFORM_API_TOKEN")
                client = PlatformBenchmarkClient(args.platform_url, token=token)
                operations = client.operations()
                release = operations.get("release")
                if isinstance(release, dict):
                    subject.metadata["platform_release"] = {
                        key: release.get(key)
                        for key in (
                            "release_id",
                            "stage",
                            "source_git_sha",
                            "migration_version",
                            "knowledge_service_contract_version",
                            "platform_api_contract_version",
                        )
                        if release.get(key) is not None
                    }
                if suite.benchmark_class == "llm" and args.track == "reasoning_fixed_evidence":
                    if args.ers_root is None:
                        raise SystemExit("fixed-evidence live run requires --ers-root")
                    artifact = run_fixed_evidence_llm(
                        client=client, suite_path=args.suite, dataset_path=args.dataset,
                        subject=subject, ai_root=args.ai_root, ers_root=args.ers_root,
                        source_revisions=revisions, model=args.model,
                        model_num_ctx=args.model_num_ctx, model_num_gpu=args.model_num_gpu,
                        splits=splits or None,
                        case_ids=case_ids or None,
                    )
                elif suite.benchmark_class == "retrieval_rag" and args.track in {
                    "retrieval_only", "retrieval_plus_reranker"
                }:
                    artifact = run_retrieval(
                        client=client, suite_path=args.suite, dataset_path=args.dataset,
                        subject=subject, track=args.track, source_revisions=revisions,
                        mode=args.knowledge_mode, limit=args.limit,
                        splits=splits or None, case_ids=case_ids or None,
                    )
                elif suite.benchmark_class == "retrieval_rag" and args.track == "end_to_end_rag":
                    artifact = run_end_to_end_rag(
                        client=client, suite_path=args.suite, dataset_path=args.dataset,
                        subject=subject, source_revisions=revisions,
                        mode=args.knowledge_mode, limit=min(args.limit, 20),
                        splits=splits or None, case_ids=case_ids or None,
                    )
                else:
                    raise SystemExit(
                        "live execution for this track requires a dedicated adapter; "
                        "dry-run remains available"
                    )

        if args.output:
            write_artifact(args.output, artifact)
        print(artifact.model_dump_json(indent=2))
        return

    plan = build_run_plan(
        args.suite,
        args.dataset,
        track=args.track,
        ai_root=args.ai_root,
        ers_root=args.ers_root,
    )
    encoded = json.dumps(plan, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
    print(encoded, end="")


if __name__ == "__main__":
    main()
