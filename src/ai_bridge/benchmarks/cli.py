"""CLI for benchmark dataset validation and reproducible run planning."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .contracts import GoldenDataset, SuiteManifest
from .coverage import CoveragePolicy, evaluate_coverage
from .provenance import validate_ers_provenance
from .run_manifest import build_run_plan


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
    return parser


def main() -> None:
    args = _parser().parse_args()
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
