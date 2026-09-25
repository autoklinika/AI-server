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

from ers_dr import copy_object_set as copy_ers_object_set
from ers_dr import fetch_snapshot_metadata as fetch_ers_snapshot_metadata

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
MARKER_SCHEMA_VERSION = 1
MIN_TARGET_FREE_BYTES = 1024 * 1024 * 1024


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
    require(marker_data.get("schema_version") == MARKER_SCHEMA_VERSION,
            "NAS marker schema mismatch")
    fs_type = run([
        "findmnt", "-T", str(root), "-n", "-o", "FSTYPE"
    ]).strip()
    require(fs_type in NETWORK_FS, f"target is not approved network FS: {fs_type}")

    usage = os.statvfs(root)
    free_bytes = usage.f_bavail * usage.f_frsize
    require(free_bytes >= MIN_TARGET_FREE_BYTES,
            "NAS target has less than 1 GiB free")

    probe = root / f".stage-k-write-probe-{os.getpid()}"
    payload = os.urandom(32)
    try:
        fd = os.open(probe, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            os.write(fd, payload)
            os.fsync(fd)
        finally:
            os.close(fd)
        require(probe.read_bytes() == payload, "NAS write/read probe mismatch")
    finally:
        try:
            probe.unlink()
        except FileNotFoundError:
            pass

    return {
        "mode": "nas",
        "filesystem": fs_type,
        "marker_schema": MARKER_SCHEMA_VERSION,
        "free_bytes_at_start": free_bytes,
        "write_read_probe": "PASS",
    }


def connect_snapshot(pg: dict[str, str]):
    import psycopg

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
    """Populate/reuse the immutable canonical pool and return set references."""
    seen: set[str] = set()
    rows: list[dict[str, object]] = []
    copied = 0
    reused = 0
    destination.mkdir(parents=True, exist_ok=True)
    for item in versions:
        digest = str(item["content_sha256"])
        require(re.fullmatch(r"[0-9a-f]{64}", digest) is not None,
                "invalid canonical SHA-256 in database")
        expected = OBJECT_ROOT / "sha256" / digest[:2] / digest
        if digest in seen:
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
        if target.exists():
            require(target.stat().st_size == int(item["byte_size"]),
                    f"NAS canonical object size mismatch: {digest}")
            require(file_sha256(target) == digest,
                    f"NAS canonical object checksum mismatch: {digest}")
            reused += 1
        else:
            tmp = target.with_name(target.name + f".tmp-{os.getpid()}")
            shutil.copy2(source, tmp)
            require(file_sha256(tmp) == digest,
                    f"copied canonical object checksum mismatch: {digest}")
            os.replace(tmp, target)
            copied += 1
        rows.append({
            "sha256": digest,
            "bytes": int(item["byte_size"]),
            "path": target.relative_to(destination).as_posix(),
        })
    return {
        "objects": len(rows),
        "bytes": sum(int(row["bytes"]) for row in rows),
        "files": rows,
        "copied_objects": copied,
        "reused_objects": reused,
        "pool_root": "Knowledge/canonical-objects",
    }

def release_identity() -> dict[str, str]:
    values: dict[str, str] = {}
    release_file = active_release() / "RELEASE"
    for raw in release_file.read_text().splitlines():
        if "=" in raw:
            key, value = raw.split("=", 1)
            values[key] = value
    require(values.get("stage") in {"J", "L"}, "active production stage is not J/L")
    require(re.fullmatch(r"[0-9a-f]{40}", values.get("source_git_sha", "")) is not None,
            "active release source SHA unavailable")
    return values


def create_backup(args) -> dict[str, Path]:
    root = args.target_root.resolve()
    require(root.name == "AI_Platform",
            "target root must be the AI_Platform directory")
    target_info = verify_target(root, args.allow_local)
    backup_id = utc_now().strftime("%Y%m%dT%H%M%SZ")

    shared_pg = root / "_Shared" / "PostgreSQL" / "ai_bridge" / args.tier / backup_id
    knowledge_final = root / "Knowledge" / "manifests" / args.tier / backup_id
    wvc_final = root / "WVC" / "manifests" / args.tier / backup_id
    ers_final = root / "ERS" / "case-store" / "manifests" / args.tier / backup_id
    staging = root / ".incomplete" / f"{backup_id}.{os.getpid()}"
    for path in (shared_pg, knowledge_final, wvc_final, ers_final):
        require(not path.exists(), "backup ID collision")
    staging.mkdir(parents=True, mode=0o700)
    dump = staging / "ai_bridge.dump"

    pg = production_postgres_env()
    started = utc_now()
    with connect_snapshot(pg) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"
            )
            cur.execute("SELECT pg_export_snapshot()")
            snapshot_id = cur.fetchone()[0]
        metadata = fetch_snapshot_metadata(conn)
        ers_snapshot = fetch_ers_snapshot_metadata(conn)
        if ers_snapshot["active"]:
            metadata["table_counts"].update(ers_snapshot["table_counts"])
        run([
            "pg_dump", "--format=custom", "--no-owner", "--no-privileges",
            f"--snapshot={snapshot_id}", f"--file={dump}",
        ], env=pg, timeout=900)
        require(dump.is_file() and dump.stat().st_size > 0, "empty PostgreSQL dump")
        run(["pg_restore", "-l", str(dump)], timeout=120)

        canonical = copy_canonical(
            metadata["versions"], root / "Knowledge" / "canonical-objects"
        )
        ers_objects = (
            copy_ers_object_set(
                ers_snapshot,
                root / "ERS" / "object-store",
                source_root=OBJECT_ROOT,
            )
            if ers_snapshot["active"]
            else None
        )
        conn.commit()

    shared_pg.mkdir(parents=True, exist_ok=False)
    final_dump = shared_pg / "ai_bridge.dump"
    os.replace(dump, final_dump)

    release = release_identity()
    common_source = {
        "hostname": socket.gethostname(),
        "machine_id_sha256": machine_identity_hash(),
        "active_release": str(active_release()),
        "release_id": release.get("release_id"),
        "runtime_source_git_sha": release["source_git_sha"],
        "stage_k_code_git_sha": git_head(),
    }
    postgres = {
        "database": metadata["database_name"],
        "server_version": metadata["postgres_version"],
        "schema_version": metadata["schema_version"],
        "dump": {
            "path": final_dump.relative_to(root).as_posix(),
            "bytes": final_dump.stat().st_size,
            "sha256": file_sha256(final_dump),
            "format": "custom",
        },
        "table_counts": metadata["table_counts"],
    }

    knowledge_manifest = {
        "manifest_schema_version": 2,
        "status": "COMPLETE",
        "domain": "Knowledge",
        "backup_id": backup_id,
        "tier": args.tier,
        "created_at": started.isoformat(),
        "completed_at": utc_now().isoformat(),
        "target": target_info,
        "layout": {"root": "AI_Platform", "shared_postgres": True},
        "source": common_source,
        "postgres": postgres,
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

    wvc_counts = {
        k: v for k, v in metadata["table_counts"].items()
        if k.startswith("ventilation_")
    }
    wvc_manifest = {
        "manifest_schema_version": 2,
        "status": "COMPLETE",
        "domain": "WVC",
        "backup_id": backup_id,
        "tier": args.tier,
        "created_at": started.isoformat(),
        "completed_at": utc_now().isoformat(),
        "target": target_info,
        "layout": {"root": "AI_Platform", "shared_postgres": True},
        "source": common_source,
        "postgres": {
            **postgres,
            "domain_table_counts": wvc_counts,
        },
        "secrets_included": False,
    }

    ers_manifest = None
    if ers_snapshot["active"]:
        ers_manifest = {
            "manifest_schema_version": 1,
            "status": "COMPLETE",
            "domain": "ERSCaseStore",
            "backup_id": backup_id,
            "tier": args.tier,
            "created_at": started.isoformat(),
            "completed_at": utc_now().isoformat(),
            "target": target_info,
            "layout": {"root": "AI_Platform", "shared_postgres": True},
            "source": common_source,
            "postgres": {
                **postgres,
                "domain_table_counts": ers_snapshot["table_counts"],
            },
            "ers": {
                "source_of_truth": "postgres+shared-object-store",
                "availability_counts": ers_snapshot["availability_counts"],
                "available_versions": ers_snapshot["available_versions"],
                "case_boundaries": ers_snapshot["case_boundaries"],
                "object_set": ers_objects,
            },
            "secrets_included": False,
        }

    manifest_sets = [
        (knowledge_final, knowledge_manifest),
        (wvc_final, wvc_manifest),
    ]
    if ers_manifest is not None:
        manifest_sets.append((ers_final, ers_manifest))

    for final, manifest in manifest_sets:
        tmp_set = staging / final.parent.parent.parent.name
        tmp_set.mkdir(parents=True, exist_ok=True)
        manifest_path = tmp_set / "manifest.json"
        atomic_text(
            manifest_path,
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        )
        atomic_text(
            tmp_set / "manifest.sha256",
            file_sha256(manifest_path) + "  manifest.json\n",
        )
        atomic_text(tmp_set / "COMPLETE", backup_id + "\n")
        final.parent.mkdir(parents=True, exist_ok=True)
        os.replace(tmp_set, final)

    try:
        staging.rmdir()
        staging.parent.rmdir()
    except OSError:
        pass
    return {
        "knowledge": knowledge_final,
        "wvc": wvc_final,
        "ers": ers_final if ers_manifest is not None else None,
        "postgres": shared_pg,
    }

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
    result = create_backup(args)
    print(json.dumps({
        "status": "PASS",
        "knowledge_set": str(result["knowledge"]),
        "wvc_set": str(result["wvc"]),
        "ers_set": str(result["ers"]) if result["ers"] is not None else None,
        "postgres_set": str(result["postgres"]),
    }, sort_keys=True))


if __name__ == "__main__":
    main()
