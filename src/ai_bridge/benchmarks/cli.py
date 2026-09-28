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
from .run_manifest import build_run_plan, git_revision
from .runner import (
    BenchmarkSubject,
    dry_run,
    run_end_to_end_rag,
    run_fixed_evidence_llm,
    run_retrieval,
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
    run.add_argument("--platform-url", default=os.getenv(
        "AI_PLATFORM_URL", "http://127.0.0.1:11435"
    ))
    run.add_argument("--knowledge-mode", choices=[
        "exact", "keyword", "semantic", "hybrid", "auto"
    ], default="hybrid")
    run.add_argument("--limit", type=int, default=10)
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

        metadata = {}
        if args.adapter == "knowledge-api-v1":
            metadata = {"knowledge_mode": args.knowledge_mode, "limit": args.limit}
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
            token = os.getenv("AI_PLATFORM_API_TOKEN")
            client = PlatformBenchmarkClient(args.platform_url, token=token)
            if suite.benchmark_class == "llm" and args.track == "reasoning_fixed_evidence":
                if args.ers_root is None:
                    raise SystemExit("fixed-evidence live run requires --ers-root")
                artifact = run_fixed_evidence_llm(
                    client=client, suite_path=args.suite, dataset_path=args.dataset,
                    subject=subject, ai_root=args.ai_root, ers_root=args.ers_root,
                    source_revisions=revisions, splits=splits or None,
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
