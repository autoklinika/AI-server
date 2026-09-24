#!/usr/bin/env python3
"""Create one atomic Stage K recovery set.

Default behavior is fail-closed for NAS targets. Local targets require an explicit
--allow-local flag and are validation-only, never production DR evidence.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import socket
from urllib.parse import urlparse

import psycopg

from common import (
    OBJECT_ROOT,
    active_release,
    atomic_text,
    file_sha256,
    git_head,
    machine_identity_hash,
    production_postgres_env,
    require,
    run,
)

NETWORK_FS = {"cifs", "nfs", "nfs4", "fuse.sshfs"}
MARKER = ".ai-platform-backup-target.json"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def verify_target(root: Path, allow_local: bool) -> dict[str, object]:
    require(root.is_dir(), f"backup target does not exist: {root}")
    marker = root / MARKER
    if allow_local:
        return {"mode": "local-validation", "filesystem": None, "marker": None}
    require(marker.is_file(), f"NAS marker missing: {marker}")
    try:
        marker_data = json.loads(marker.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("invalid NAS marker") from exc
    require(marker_data.get("purpose") == "ai-platform-stage-k",
            "NAS marker purpose mismatch")
    fs_type = run([
        "findmnt", "-T", str(root), "-n", "-o", "FSTYPE"
    ]).strip()
    require(fs_type in NETWORK_FS, f"target is not approved network FS: {fs_type}")
    return {
        "mode": "nas",
        "filesystem": fs_type,
        "marker_schema": marker_data.get("schema_version"),
    }


def connect_snapshot(pg: dict[str, str]):
    return psycopg.connect(
        host=pg["PGHOST"],
        port=int(pg["PGPORT"]),
        user=pg["PGUSER"],
        password=pg["PGPASSWORD"],
        dbname=pg["PGDATABASE"],
        autocommit=False,
    )


def fetch_snapshot_metadata(conn) -> dict[str, object]:
    with conn.cursor() as cur:
        cur.execute("SELECT version_num FROM alembic_version")
        schema_version = cur.fetchone()[0]
        tables = (
            "knowledge_sources",
            "knowledge_documents",
            "knowledge_document_versions",
            "knowledge_chunks",
            "knowledge_index_jobs",
            "ventilation_ingest_batches",
            "ventilation_telemetry_raw",
            "ventilation_analysis_runs",
        )
        counts: dict[str, int] = {}
        for table in tables:
            cur.execute(f"SELECT count(*) FROM {table}")
            counts[table] = int(cur.fetchone()[0])
        cur.execute(
            "SELECT state, count(*) FROM knowledge_index_jobs "
            "GROUP BY state ORDER BY state"
        )
        index_states = {row[0]: int(row[1]) for row in cur.fetchall()}
        cur.execute(
            "SELECT count(*) FROM knowledge_chunks c "
            "JOIN knowledge_documents d ON d.current_version_id = c.version_id"
        )
        current_chunks = int(cur.fetchone()[0])
        cur.execute("SELECT current_database(), current_setting('server_version')")
        database_name, pg_version = cur.fetchone()
        cur.execute(
            "SELECT version_id, content_sha256, byte_size, storage_uri "
            "FROM knowledge_document_versions ORDER BY version_id"
        )
        versions = [
            {
                "version_id": row[0],
                "content_sha256": row[1],
                "byte_size": int(row[2]),
                "storage_uri": row[3],
            }
            for row in cur.fetchall()
        ]
    return {
        "database_name": database_name,
        "postgres_version": pg_version,
        "schema_version": schema_version,
        "table_counts": counts,
        "index_states": index_states,
        "current_chunks": current_chunks,
        "versions": versions,
    }


def copy_canonical(versions: list[dict[str, object]], destination: Path) -> dict[str, object]:
    seen: set[str] = set()
    rows: list[dict[str, object]] = []
    destination.mkdir(parents=True)
    for item in versions:
        digest = str(item["content_sha256"])
        require(re.fullmatch(r"[0-9a-f]{64}", digest) is not None,
                "invalid canonical SHA-256 in database")
        expected = OBJECT_ROOT / "sha256" / digest[:2] / digest
        if digest in seen:
            require(expected.is_file(), f"canonical object missing: {digest}")
            require(expected.stat().st_size == int(item["byte_size"]),
                    f"canonical object size mismatch: {digest}")
            require(file_sha256(expected) == digest,
                    f"canonical object checksum mismatch: {digest}")
            continue
        seen.add(digest)
        parsed = urlparse(str(item["storage_uri"]))
        source = Path(parsed.path if parsed.scheme == "file" else str(item["storage_uri"]))
        require(source.resolve() == expected.resolve(),
                "storage URI does not match content-addressed object path")
        require(source.is_file(), f"canonical object missing: {digest}")
        require(source.stat().st_size == int(item["byte_size"]),
                f"canonical object size mismatch: {digest}")
        require(file_sha256(source) == digest,
                f"canonical object checksum mismatch: {digest}")
        target = destination / "sha256" / digest[:2] / digest
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        require(file_sha256(target) == digest,
                f"copied canonical object checksum mismatch: {digest}")
        rows.append({
            "sha256": digest,
            "bytes": int(item["byte_size"]),
            "path": target.relative_to(destination).as_posix(),
        })
    return {
        "objects": len(rows),
        "bytes": sum(int(row["bytes"]) for row in rows),
        "files": rows,
    }


def release_identity() -> dict[str, str]:
    values: dict[str, str] = {}
    release_file = active_release() / "RELEASE"
    for raw in release_file.read_text().splitlines():
        if "=" in raw:
            key, value = raw.split("=", 1)
            values[key] = value
    require(values.get("stage") == "J", "active production stage is not J")
    require(re.fullmatch(r"[0-9a-f]{40}", values.get("source_git_sha", "")) is not None,
            "active release source SHA unavailable")
    return values


def create_backup(args) -> Path:
    root = args.target_root.resolve()
    target_info = verify_target(root, args.allow_local)
    backup_id = utc_now().strftime("%Y%m%dT%H%M%SZ")
    final_parent = root / "AI-Server" / "sets" / args.tier
    staging_parent = root / "AI-Server" / ".incomplete"
    final_parent.mkdir(parents=True, exist_ok=True)
    staging_parent.mkdir(parents=True, exist_ok=True)
    staging = staging_parent / f"{backup_id}.{os.getpid()}"
    final = final_parent / backup_id
    require(not final.exists(), "backup ID collision")
    staging.mkdir(mode=0o700)
    pg_dir = staging / "postgres"
    objects_dir = staging / "knowledge" / "canonical-objects"
    pg_dir.mkdir(parents=True)

    pg = production_postgres_env()
    dump = pg_dir / "ai_bridge.dump"
    started = utc_now()
    with connect_snapshot(pg) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"
            )
            cur.execute("SELECT pg_export_snapshot()")
            snapshot_id = cur.fetchone()[0]
        metadata = fetch_snapshot_metadata(conn)
        run([
            "pg_dump", "--format=custom", "--no-owner", "--no-privileges",
            f"--snapshot={snapshot_id}", f"--file={dump}",
        ], env=pg, timeout=900)
        require(dump.is_file() and dump.stat().st_size > 0, "empty PostgreSQL dump")
        run(["pg_restore", "-l", str(dump)], timeout=120)
        canonical = copy_canonical(metadata["versions"], objects_dir)
        conn.commit()


    release = release_identity()
    manifest = {
        "manifest_schema_version": 1,
        "status": "COMPLETE",
        "backup_id": backup_id,
        "tier": args.tier,
        "created_at": started.isoformat(),
        "completed_at": utc_now().isoformat(),
        "target": target_info,
        "source": {
            "hostname": socket.gethostname(),
            "machine_id_sha256": machine_identity_hash(),
            "active_release": str(active_release()),
            "release_id": release.get("release_id"),
            "runtime_source_git_sha": release["source_git_sha"],
            "stage_k_code_git_sha": git_head(),
        },
        "postgres": {
            "database": metadata["database_name"],
            "server_version": metadata["postgres_version"],
            "schema_version": metadata["schema_version"],
            "dump": {
                "path": "postgres/ai_bridge.dump",
                "bytes": dump.stat().st_size,
                "sha256": file_sha256(dump),
                "format": "custom",
            },
            "table_counts": metadata["table_counts"],
        },
        "knowledge": {
            "source_of_truth": "postgres+canonical-objects",
            "versions": len(metadata["versions"]),
            "chunks": metadata["table_counts"]["knowledge_chunks"],
            "current_chunks": metadata["current_chunks"],
            "index_job_states": metadata["index_states"],
            "canonical": canonical,
            "qdrant_required_for_restore": False,
        },
        "secrets_included": False,
    }
    manifest_path = staging / "manifest.json"
    atomic_text(
        manifest_path,
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
    )
    atomic_text(
        staging / "manifest.sha256",
        file_sha256(manifest_path) + "  manifest.json\n",
    )
    atomic_text(staging / "COMPLETE", backup_id + "\n")
    os.replace(staging, final)
    return final


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target-root", type=Path, required=True)
    parser.add_argument("--tier", choices=("daily", "weekly", "manual"),
                        default="manual")
    parser.add_argument(
        "--allow-local", action="store_true",
        help="validation only: permit a non-network target",
    )
    args = parser.parse_args()
    final = create_backup(args)
    print(json.dumps({"status": "PASS", "backup_set": str(final)}))


if __name__ == "__main__":
    main()
