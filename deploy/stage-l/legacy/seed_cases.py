#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys

from ai_bridge.domains.ers.legacy_seed import (
    ErsLegacySeedConflict,
    ErsLegacySeedInvalid,
    LegacySeedImporter,
)
from ai_bridge.storage.database import Database
from ai_bridge.storage.object_store import FileObjectStore


def git_revision(root: Path) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        check=True,
        text=True,
        capture_output=True,
    )
    return result.stdout.strip()


def require_clean_tracked(root: Path) -> None:
    result = subprocess.run(
        ["git", "-C", str(root), "status", "--porcelain", "--untracked-files=no"],
        check=True,
        text=True,
        capture_output=True,
    )
    if result.stdout.strip():
        raise RuntimeError("source root has tracked modifications")


def seed_paths(root: Path, selected: list[str]) -> list[Path]:
    if selected:
        paths = [(root / value).resolve() for value in selected]
    else:
        paths = sorted((root / "cases").glob("*/case.seed.json"))
    if not paths:
        raise RuntimeError("no case.seed.json files found")
    return paths


def plan_payload(plan) -> dict:
    return {
        "legacy_case_code": plan.seed.legacy_case_code,
        "title": plan.seed.title,
        "fingerprint": plan.fingerprint,
        "source_revision": plan.source_revision,
        "seed_path": str(plan.seed_path),
        "artifacts": [
            {
                "path": item.artifact.path,
                "source_kind": item.artifact.source_kind,
                "byte_size": item.byte_size,
                "sha256": item.sha256,
            }
            for item in plan.artifacts
        ],
        "final_status": plan.seed.final_status,
        "final_work_state": plan.seed.final_work_state,
    }

def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)

    for command in ("plan", "apply"):
        item = sub.add_parser(command)
        item.add_argument("--source-root", type=Path, required=True)
        item.add_argument(
            "--seed",
            action="append",
            default=[],
            help="relative case.seed.json path; repeatable",
        )
        item.add_argument("--source-revision")

    apply_parser = sub.choices["apply"]
    apply_parser.add_argument("--database-url", required=True)
    apply_parser.add_argument("--object-store-root", type=Path, required=True)

    args = parser.parse_args()
    root = args.source_root.resolve()
    if not root.is_dir():
        raise SystemExit("source root does not exist")

    require_clean_tracked(root)
    revision = args.source_revision or git_revision(root)
    paths = seed_paths(root, args.seed)

    planner = LegacySeedImporter()
    plans = [
        planner.plan(path, source_revision=revision)
        for path in paths
    ]

    if args.command == "plan":
        print(json.dumps({
            "status": "PASS",
            "mode": "plan",
            "source_root": str(root),
            "source_revision": revision,
            "cases": [plan_payload(plan) for plan in plans],
        }, indent=2, sort_keys=True, default=str))
        return

    database = Database(args.database_url)
    store = FileObjectStore(args.object_store_root.resolve())
    importer = LegacySeedImporter(database=database, object_store=store)
    try:
        outcomes = [importer.apply(plan) for plan in plans]
    finally:
        database.dispose()

    print(json.dumps({
        "status": "PASS",
        "mode": "apply",
        "source_root": str(root),
        "source_revision": revision,
        "cases": [
            {
                "case_id": str(row.case_id),
                "case_code": row.case_code,
                "legacy_case_code": row.legacy_case_code,
                "fingerprint": row.fingerprint,
                "artifacts": row.artifacts,
                "state": row.state,
                "object_hashes": list(row.object_hashes),
            }
            for row in outcomes
        ],
    }, indent=2, sort_keys=True))

if __name__ == "__main__":
    try:
        main()
    except (ErsLegacySeedInvalid, ErsLegacySeedConflict, RuntimeError) as exc:
        print(
            json.dumps({
                "status": "FAIL",
                "error": type(exc).__name__,
                "detail": str(exc),
            }, sort_keys=True),
            file=sys.stderr,
        )
        raise SystemExit(64)
