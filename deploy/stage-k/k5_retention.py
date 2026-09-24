#!/usr/bin/env python3
"""Fail-closed retention for Stage K automatic backup tiers."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil

from common import require

DEFAULT_ROOT = Path("/mnt/AI_Platform")
K2_DOMAINS = (
    ("Knowledge", "manifests"),
    ("WVC", "manifests"),
)
K3_DOMAINS = (
    ("ERS", "manifests"),
    ("Hermes", "manifests"),
    ("Platform", "manifests"),
)


def complete_ids(path: Path, tier: str) -> list[str]:
    root = path / tier
    if not root.is_dir():
        return []
    result: list[str] = []
    for item in root.iterdir():
        if not item.is_dir():
            continue
        manifest = item / "manifest.json"
        complete = item / "COMPLETE"
        if not manifest.is_file() or not complete.is_file():
            continue
        data = json.loads(manifest.read_text())
        require(data.get("status") == "COMPLETE", f"invalid manifest status: {item}")
        require(data.get("backup_id") == item.name, f"backup id/path mismatch: {item}")
        require(complete.read_text().strip() == item.name, f"COMPLETE mismatch: {item}")
        result.append(item.name)
    return sorted(result, reverse=True)


def remove_checked(path: Path, backup_id: str) -> None:
    if not path.exists():
        return
    require(path.is_dir(), f"retention target is not directory: {path}")
    shutil.rmtree(path)


def prune_k2(root: Path, tier: str, keep: int) -> list[str]:
    knowledge = root / "Knowledge" / "manifests"
    ids = complete_ids(knowledge, tier)
    expired = ids[keep:]
    for backup_id in expired:
        for domain, manifests in K2_DOMAINS:
            mdir = root / domain / manifests / tier / backup_id
            require(mdir.is_dir(), f"missing paired K2 manifest: {mdir}")
            require((mdir / "COMPLETE").read_text().strip() == backup_id,
                    f"paired K2 COMPLETE mismatch: {mdir}")
        dbdir = root / "_Shared" / "PostgreSQL" / "ai_bridge" / tier / backup_id
        require((dbdir / "ai_bridge.dump").is_file(),
                f"paired K2 PostgreSQL dump missing: {backup_id}")
        for domain, manifests in K2_DOMAINS:
            remove_checked(root / domain / manifests / tier / backup_id, backup_id)
        remove_checked(dbdir, backup_id)
    return expired
def prune_k3(root: Path, tier: str, keep: int) -> list[str]:
    ers = root / "ERS" / "manifests"
    ids = complete_ids(ers, tier)
    expired = ids[keep:]
    for backup_id in expired:
        for domain, manifests in K3_DOMAINS:
            mdir = root / domain / manifests / tier / backup_id
            require(mdir.is_dir(), f"missing paired K3 manifest: {mdir}")
            require((mdir / "COMPLETE").read_text().strip() == backup_id,
                    f"paired K3 COMPLETE mismatch: {mdir}")

        pairs = (
            root / "ERS" / "snapshots" / tier / backup_id,
            root / "Hermes" / "snapshots" / tier / backup_id,
            root / "Platform" / "config" / "snapshots" / tier / backup_id,
        )
        for snapshot in pairs:
            require(snapshot.is_dir(), f"paired K3 snapshot missing: {snapshot}")

        for domain, manifests in K3_DOMAINS:
            remove_checked(root / domain / manifests / tier / backup_id, backup_id)
        for snapshot in pairs:
            remove_checked(snapshot, backup_id)
    return expired


def prune_restore_evidence(keep_weekly: int) -> list[str]:
    root = Path("/srv/ai-data/backups/stage-k/restore-validation")
    if not root.is_dir():
        return []
    candidates: list[Path] = []
    for item in root.iterdir():
        if not item.is_dir() or not (item / "PASS").is_file():
            continue
        source = item / "source-backup.txt"
        if not source.is_file():
            continue
        if "/weekly/" in source.read_text(errors="replace"):
            candidates.append(item)
    candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    expired = candidates[keep_weekly:]
    for item in expired:
        shutil.rmtree(item)
    return [item.name for item in expired]


def apply(root: Path, tier: str, keep: int, evidence_keep: int) -> dict[str, object]:
    require(root.name == "AI_Platform", "target root must be AI_Platform")
    require(tier in {"daily", "weekly"}, "retention only applies to automatic tiers")
    return {
        "status": "PASS",
        "tier": tier,
        "keep": keep,
        "removed_k2": prune_k2(root, tier, keep),
        "removed_k3": prune_k3(root, tier, keep),
        "removed_restore_evidence": (
            prune_restore_evidence(evidence_keep) if tier == "weekly" else []
        ),
        "canonical_pool_gc": "disabled",
        "manual_sets_touched": False,
        "secrets_sets_touched": False,
    }
def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target-root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--tier", choices=("daily", "weekly"), required=True)
    parser.add_argument("--keep", type=int, required=True)
    parser.add_argument("--restore-evidence-keep", type=int, default=12)
    args = parser.parse_args()
    require(args.keep > 0, "keep must be positive")
    require(args.restore_evidence_keep > 0, "restore evidence keep must be positive")
    print(json.dumps(
        apply(args.target_root.resolve(), args.tier, args.keep, args.restore_evidence_keep),
        sort_keys=True,
    ))


if __name__ == "__main__":
    main()
