#!/usr/bin/env python3
"""Offline integrity verification for a completed Stage K backup set."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re

from common import file_sha256, require, run


def platform_root(backup: Path) -> Path:
    backup = backup.resolve()
    for candidate in (backup, *backup.parents):
        if candidate.name == "AI_Platform":
            return candidate
    raise RuntimeError("backup set is not below AI_Platform root")


def resolve_from_root(backup: Path, relative: str) -> Path:
    root = platform_root(backup)
    path = (root / relative).resolve()
    require(path == root or root in path.parents,
            "manifest path escapes AI_Platform root")
    return path


def verify(backup: Path) -> dict[str, object]:
    backup = backup.resolve()
    complete = backup / "COMPLETE"
    manifest_path = backup / "manifest.json"
    manifest_sum = backup / "manifest.sha256"
    require(complete.is_file(), "backup set is not COMPLETE")
    require(manifest_path.is_file(), "manifest.json missing")
    require(manifest_sum.is_file(), "manifest.sha256 missing")

    expected_manifest_hash = manifest_sum.read_text().split()[0]
    require(re.fullmatch(r"[0-9a-f]{64}", expected_manifest_hash) is not None,
            "invalid manifest checksum")
    require(file_sha256(manifest_path) == expected_manifest_hash,
            "manifest checksum mismatch")
    manifest = json.loads(manifest_path.read_text())
    require(manifest.get("status") == "COMPLETE", "manifest status is not COMPLETE")
    require(manifest.get("domain") in {"Knowledge", "WVC"},
            "unsupported Stage K domain manifest")
    require(complete.read_text().strip() == manifest.get("backup_id"),
            "COMPLETE marker/manifest mismatch")
    require(manifest.get("secrets_included") is False,
            "plain backup set must not include secrets")

    dump_meta = manifest["postgres"]["dump"]
    dump = resolve_from_root(backup, dump_meta["path"])
    require(dump.is_file(), "PostgreSQL dump missing")
    require(dump.stat().st_size == int(dump_meta["bytes"]),
            "PostgreSQL dump size mismatch")
    require(file_sha256(dump) == dump_meta["sha256"],
            "PostgreSQL dump checksum mismatch")
    run(["pg_restore", "-l", str(dump)], timeout=120)

    result = {
        "status": "PASS",
        "domain": manifest["domain"],
        "backup_id": manifest["backup_id"],
        "postgres_dump_bytes": dump.stat().st_size,
    }

    if manifest["domain"] == "WVC":
        domain_counts = manifest["postgres"].get("domain_table_counts", {})
        require(bool(domain_counts), "WVC manifest has no domain table counts")
        for table, count in domain_counts.items():
            require(table.startswith("ventilation_"),
                    "WVC manifest references a non-WVC table")
            require(
                int(manifest["postgres"]["table_counts"][table]) == int(count),
                f"WVC table count mismatch in manifest: {table}",
            )
        result["wvc_table_counts"] = domain_counts
        return result

    canonical = manifest["knowledge"]["canonical"]
    pool = resolve_from_root(backup, canonical["pool_root"])
    files = canonical["files"]
    total_bytes = 0
    seen: set[str] = set()
    for item in files:
        digest = item["sha256"]
        require(re.fullmatch(r"[0-9a-f]{64}", digest) is not None,
                "invalid canonical checksum in manifest")
        require(digest not in seen, "duplicate canonical manifest entry")
        seen.add(digest)
        path = (pool / item["path"]).resolve()
        require(pool == path or pool in path.parents,
                "canonical manifest path escapes pool")
        require(path.is_file(), f"canonical object missing: {digest}")
        require(path.stat().st_size == int(item["bytes"]),
                f"canonical object size mismatch: {digest}")
        require(file_sha256(path) == digest,
                f"canonical object checksum mismatch: {digest}")
        total_bytes += path.stat().st_size

    require(len(files) == int(canonical["objects"]),
            "canonical manifest count mismatch")
    require(total_bytes == int(canonical["bytes"]),
            "canonical byte count mismatch")
    result.update({
        "canonical_objects": len(files),
        "canonical_bytes": total_bytes,
        "canonical_pool_objects_total": sum(
            1 for item in pool.rglob("*") if item.is_file()
        ),
        "knowledge_versions": manifest["knowledge"]["versions"],
        "knowledge_chunks": manifest["knowledge"]["chunks"],
    })
    return result

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("backup_set", type=Path)
    args = parser.parse_args()
    print(json.dumps(verify(args.backup_set), sort_keys=True))


if __name__ == "__main__":
    main()
