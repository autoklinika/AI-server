#!/usr/bin/env python3
"""ERS Case Store backup metadata and immutable object-set helpers.

The PostgreSQL dump remains shared with Knowledge/WVC. This module adds an ERS
manifest view over the same database snapshot plus the exact content-addressed
objects referenced by available ERS artifact versions.
"""
from __future__ import annotations

import os
from pathlib import Path
import re
import shutil
from typing import Any

from common import OBJECT_ROOT, file_sha256, require


CORE_ERS_TABLES = {
    "ers_case_counters",
    "ers_cases",
    "ers_case_events",
    "ers_assets",
    "ers_asset_revisions",
    "ers_case_assets",
    "ers_ecus",
    "ers_case_ecus",
    "ers_ecu_identity_observations",
    "ers_ecu_software_observations",
    "ers_symptoms",
    "ers_dtcs",
    "ers_measurements",
    "ers_diagnostic_steps",
    "ers_hypotheses",
    "ers_hypothesis_evidence",
    "ers_repair_actions",
    "ers_case_results",
    "ers_provenance_records",
    "ers_provenance_edges",
    "ers_evidence",
    "ers_artifacts",
    "ers_artifact_versions",
}
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def fetch_snapshot_metadata(conn) -> dict[str, Any]:
    """Read ERS metadata inside the caller's exported read-only DB snapshot."""
    with conn.cursor() as cur:
        cur.execute("SELECT to_regclass('public.ers_cases')")
        if cur.fetchone()[0] is None:
            return {
                "active": False,
                "table_counts": {},
                "availability_counts": {},
                "available_versions": 0,
                "objects": [],
                "case_boundaries": [],
            }

        cur.execute(
            "SELECT tablename FROM pg_tables "
            "WHERE schemaname='public' AND tablename LIKE 'ers_%' "
            "ORDER BY tablename"
        )
        tables = [str(row[0]) for row in cur.fetchall()]
        missing = sorted(CORE_ERS_TABLES.difference(tables))
        require(not missing, "ERS schema incomplete: " + ",".join(missing))

        counts: dict[str, int] = {}
        for table in tables:
            require(re.fullmatch(r"ers_[a-z0-9_]+", table) is not None,
                    f"invalid ERS table name: {table}")
            cur.execute(f'SELECT count(*) FROM "{table}"')
            counts[table] = int(cur.fetchone()[0])

        cur.execute(
            "SELECT availability, count(*) "
            "FROM ers_artifact_versions GROUP BY availability ORDER BY availability"
        )
        availability = {str(row[0]): int(row[1]) for row in cur.fetchall()}

        cur.execute(
            "SELECT object_sha256, byte_size, count(*) "
            "FROM ers_artifact_versions "
            "WHERE availability='available' "
            "GROUP BY object_sha256, byte_size "
            "ORDER BY object_sha256, byte_size"
        )
        objects: list[dict[str, Any]] = []
        referenced_versions = 0
        by_digest: dict[str, int] = {}
        for digest_raw, size_raw, refs_raw in cur.fetchall():
            digest = "" if digest_raw is None else str(digest_raw)
            size = int(size_raw)
            refs = int(refs_raw)
            require(_SHA256.fullmatch(digest) is not None,
                    "available ERS artifact has invalid SHA-256")
            require(size >= 0, "available ERS artifact has negative byte size")
            existing = by_digest.get(digest)
            require(existing is None or existing == size,
                    f"ERS object has conflicting byte sizes: {digest}")
            by_digest[digest] = size
            referenced_versions += refs
            objects.append({
                "sha256": digest,
                "bytes": size,
                "referenced_versions": refs,
            })

        cur.execute(
            "SELECT c.id::text, c.row_version, count(e.id), "
            "COALESCE(max(e.event_seq), 0), COALESCE(min(e.event_seq), 0) "
            "FROM ers_cases c "
            "LEFT JOIN ers_case_events e ON e.case_id=c.id "
            "GROUP BY c.id, c.row_version ORDER BY c.id"
        )
        boundaries = [
            {
                "case_id": str(case_id),
                "row_version": int(row_version),
                "event_count": int(event_count),
                "max_event_seq": int(max_seq),
                "min_event_seq": int(min_seq),
            }
            for case_id, row_version, event_count, max_seq, min_seq in cur.fetchall()
        ]
        for row in boundaries:
            require(row["row_version"] == row["event_count"],
                    f"ERS case event count mismatch: {row['case_id']}")
            require(
                (row["event_count"] == 0 and row["min_event_seq"] == 0 and row["max_event_seq"] == 0)
                or (
                    row["event_count"] > 0
                    and row["min_event_seq"] == 1
                    and row["max_event_seq"] == row["row_version"]
                ),
                f"ERS case event sequence boundary mismatch: {row['case_id']}",
            )

    return {
        "active": True,
        "table_counts": counts,
        "availability_counts": availability,
        "available_versions": referenced_versions,
        "objects": objects,
        "case_boundaries": boundaries,
    }


def copy_object_set(
    snapshot: dict[str, Any],
    destination: Path,
    *,
    source_root: Path = OBJECT_ROOT,
) -> dict[str, Any]:
    """Copy/reuse the exact ERS object set into an append-only NAS pool."""
    require(bool(snapshot.get("active")), "ERS object copy requires active snapshot")
    destination.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    copied = 0
    reused = 0

    for item in snapshot["objects"]:
        digest = str(item["sha256"])
        expected_bytes = int(item["bytes"])
        source = source_root / "sha256" / digest[:2] / digest
        require(source.is_file(), f"ERS object missing: {digest}")
        require(source.stat().st_size == expected_bytes,
                f"ERS object size mismatch: {digest}")
        require(file_sha256(source) == digest,
                f"ERS object checksum mismatch: {digest}")

        relative = Path("sha256") / digest[:2] / digest
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            require(target.stat().st_size == expected_bytes,
                    f"NAS ERS object size mismatch: {digest}")
            require(file_sha256(target) == digest,
                    f"NAS ERS object checksum mismatch: {digest}")
            reused += 1
        else:
            tmp = target.with_name(target.name + f".tmp-{os.getpid()}")
            shutil.copy2(source, tmp)
            require(file_sha256(tmp) == digest,
                    f"copied ERS object checksum mismatch: {digest}")
            os.replace(tmp, target)
            copied += 1
        rows.append({
            "sha256": digest,
            "bytes": expected_bytes,
            "path": relative.as_posix(),
            "referenced_versions": int(item["referenced_versions"]),
        })

    return {
        "objects": len(rows),
        "bytes": sum(int(row["bytes"]) for row in rows),
        "referenced_versions": sum(int(row["referenced_versions"]) for row in rows),
        "files": rows,
        "copied_objects": copied,
        "reused_objects": reused,
        "pool_root": "ERS/object-store",
    }


def validate_object_set(
    manifest_dir: Path,
    manifest: dict[str, Any],
    *,
    resolve_from_root,
) -> dict[str, int]:
    object_set = manifest["ers"]["object_set"]
    pool = resolve_from_root(manifest_dir, object_set["pool_root"])
    rows = object_set["files"]
    seen: set[str] = set()
    total_bytes = 0
    references = 0
    for item in rows:
        digest = str(item["sha256"])
        require(_SHA256.fullmatch(digest) is not None,
                "invalid ERS object checksum in manifest")
        require(digest not in seen, "duplicate ERS object manifest entry")
        seen.add(digest)
        path = (pool / str(item["path"])).resolve()
        require(path == pool or pool in path.parents,
                "ERS object path escapes pool")
        require(path.is_file(), f"ERS backup object missing: {digest}")
        require(path.stat().st_size == int(item["bytes"]),
                f"ERS backup object size mismatch: {digest}")
        require(file_sha256(path) == digest,
                f"ERS backup object checksum mismatch: {digest}")
        total_bytes += path.stat().st_size
        references += int(item["referenced_versions"])

    require(len(rows) == int(object_set["objects"]),
            "ERS object manifest count mismatch")
    require(total_bytes == int(object_set["bytes"]),
            "ERS object manifest byte count mismatch")
    require(references == int(object_set["referenced_versions"]),
            "ERS object manifest reference count mismatch")
    return {
        "objects": len(rows),
        "bytes": total_bytes,
        "referenced_versions": references,
        "pool_objects_total": (
            sum(1 for item in pool.rglob("*") if item.is_file()) if pool.is_dir() else 0
        ),
    }
