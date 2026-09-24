#!/usr/bin/env python3
"""Offline integrity verification for a completed Stage K backup set."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re

from common import file_sha256, require, run


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
    require(complete.read_text().strip() == manifest.get("backup_id"),
            "COMPLETE marker/manifest mismatch")
    require(manifest.get("secrets_included") is False,
            "plain backup set must not include secrets")

    dump_meta = manifest["postgres"]["dump"]
    dump = backup / dump_meta["path"]
    require(dump.is_file(), "PostgreSQL dump missing")
    require(dump.stat().st_size == int(dump_meta["bytes"]),
            "PostgreSQL dump size mismatch")
    require(file_sha256(dump) == dump_meta["sha256"],
            "PostgreSQL dump checksum mismatch")
    run(["pg_restore", "-l", str(dump)], timeout=120)


    canonical = manifest["knowledge"]["canonical"]
    root = backup / "knowledge" / "canonical-objects"
    files = canonical["files"]
    total_bytes = 0
    seen: set[str] = set()
    for item in files:
        digest = item["sha256"]
        require(re.fullmatch(r"[0-9a-f]{64}", digest) is not None,
                "invalid canonical checksum in manifest")
        require(digest not in seen, "duplicate canonical manifest entry")
        seen.add(digest)
        path = root / item["path"]
        require(path.is_file(), f"canonical object missing: {digest}")
        require(path.stat().st_size == int(item["bytes"]),
                f"canonical object size mismatch: {digest}")
        require(file_sha256(path) == digest,
                f"canonical object checksum mismatch: {digest}")
        total_bytes += path.stat().st_size
    actual_files = [item for item in root.rglob("*") if item.is_file()]
    require(len(actual_files) == int(canonical["objects"]),
            "unexpected canonical object count")
    require(len(files) == int(canonical["objects"]),
            "canonical manifest count mismatch")
    require(total_bytes == int(canonical["bytes"]),
            "canonical byte count mismatch")

    return {
        "status": "PASS",
        "backup_id": manifest["backup_id"],
        "postgres_dump_bytes": dump.stat().st_size,
        "canonical_objects": len(files),
        "canonical_bytes": total_bytes,
        "knowledge_versions": manifest["knowledge"]["versions"],
        "knowledge_chunks": manifest["knowledge"]["chunks"],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("backup_set", type=Path)
    args = parser.parse_args()
    print(json.dumps(verify(args.backup_set), sort_keys=True))


if __name__ == "__main__":
    main()
