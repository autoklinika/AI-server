"""Reproducible benchmark run metadata."""
from __future__ import annotations

import hashlib
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from .contracts import GoldenDataset, SuiteManifest


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_revision(path: Path) -> str | None:
    if not (path / ".git").exists():
        return None
    return subprocess.check_output(
        ["git", "-C", str(path), "rev-parse", "HEAD"],
        text=True,
    ).strip()


def build_run_plan(
    suite_path: Path,
    dataset_path: Path,
    *,
    track: str,
    ai_root: Path,
    ers_root: Path | None = None,
) -> dict:
    suite = SuiteManifest.load(suite_path)
    if track not in suite.tracks:
        raise ValueError(f"unsupported track {track!r} for {suite.suite_id}")
    dataset = GoldenDataset.load_jsonl(dataset_path)
    if not any(suite.benchmark_class in case.targets for case in dataset.cases):
        raise ValueError("dataset has no cases for suite benchmark_class")
    sources = {"ai_server_commit": git_revision(ai_root)}
    if ers_root is not None:
        sources["ers_commit"] = git_revision(ers_root)
    return {
        "schema_version": 1,
        "created_at": datetime.now(UTC).isoformat(),
        "suite": suite.model_dump(),
        "track": track,
        "dataset": {
            "path": dataset_path.as_posix(),
            "sha256": sha256_file(dataset_path),
            "summary": dataset.summary(),
        },

        "sources": sources,
        "execution_contract": {
            "resource_manager_required": True,
            "direct_provider_bypass_allowed": False,
            "baseline_required_before_training": True,
            "training_allowed_by_this_plan": False,
        },
    }
