#!/usr/bin/env python3
"""Isolated Stage K restore validation.

Restores a completed backup set into a user-owned PostgreSQL cluster, copies the
canonical store, rebuilds a brand-new Qdrant index, then runs Search/RAG/source
opening probes. Production PostgreSQL and production Qdrant are never modified.
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
import sys
import time
from uuid import uuid4

import httpx
import psycopg

from common import active_release, atomic_text, file_sha256, require, run
from verify_backup import resolve_from_root, verify as verify_backup

PG_BIN = Path("/usr/lib/postgresql/18/bin")
RESTORE_ROOT = Path("/srv/ai-data/backups/stage-k/restore-validation")


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def pg_command_env(port: int, user: str, database: str | None = None) -> dict[str, str]:
    env = {
        "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
        "LANG": "C.UTF-8",
        "PGHOST": "127.0.0.1",
        "PGPORT": str(port),
        "PGUSER": user,
    }
    if database is not None:
        env["PGDATABASE"] = database
    return env


def start_postgres(root: Path) -> tuple[int, str, str]:
    pgdata = root / "postgres-data"
    socket_dir = Path("/tmp")
    log = root / "postgres.log"
    user = "stagek_restore"
    port = free_port()
    run([
        str(PG_BIN / "initdb"),
        "-D", str(pgdata),
        "--username", user,
        "--auth-local=trust",
        "--auth-host=trust",
        "--no-locale",
        "--encoding=UTF8",
    ], timeout=120)
    run([
        str(PG_BIN / "pg_ctl"),
        "-D", str(pgdata),
        "-l", str(log),
        "-o", f"-p {port} -h 127.0.0.1 -k {socket_dir}",
        "start",
    ], timeout=60)
    env = pg_command_env(port, user)
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        try:
            run([str(PG_BIN / "pg_isready")], env=env, timeout=3)
            return port, user, str(pgdata)
        except Exception:
            time.sleep(0.25)
    raise RuntimeError("isolated PostgreSQL did not become ready")


def stop_postgres(pgdata: str) -> None:
    try:
        run([str(PG_BIN / "pg_ctl"), "-D", pgdata, "-m", "fast", "stop"], timeout=60)
    except Exception:
        pass


def restore_database(
    backup: Path, manifest: dict[str, object], port: int, user: str
) -> str:
    database = "ai_bridge_restore"
    env = pg_command_env(port, user)
    run([str(PG_BIN / "createdb"), database], env=env, timeout=60)
    dump = resolve_from_root(backup, manifest["postgres"]["dump"]["path"])
    run([
        "pg_restore",
        "--no-owner",
        "--no-privileges",
        "--exit-on-error",
        f"--dbname={database}",
        str(dump),
    ], env=pg_command_env(port, user, database), timeout=900)
    return database


def restore_objects(
    backup: Path, root: Path, manifest: dict[str, object]
) -> Path:
    canonical = manifest["knowledge"]["canonical"]
    source_pool = resolve_from_root(backup, canonical["pool_root"])
    target = root / "canonical-objects"
    for item in canonical["files"]:
        source = source_pool / item["path"]
        destination = target / item["path"]
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
    return target


def restore_ers_objects(
    manifest_dir: Path,
    root: Path,
    manifest: dict[str, object],
) -> Path:
    object_set = manifest["ers"]["object_set"]
    source_pool = resolve_from_root(manifest_dir, object_set["pool_root"])
    target = root / "ers-object-store"
    for item in object_set["files"]:
        source = (source_pool / item["path"]).resolve()
        require(source_pool == source or source_pool in source.parents,
                "ERS source object escapes pool")
        destination = target / item["path"]
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        require(destination.stat().st_size == int(item["bytes"]),
                f"restored ERS object size mismatch: {item['sha256']}")
        require(file_sha256(destination) == item["sha256"],
                f"restored ERS object checksum mismatch: {item['sha256']}")
    return target


def verify_restored_ers(
    *,
    port: int,
    user: str,
    database: str,
    object_root: Path,
    manifest: dict[str, object],
) -> dict[str, object]:
    expected_counts = manifest["postgres"]["domain_table_counts"]
    restored_counts: dict[str, int] = {}
    with restore_conn(port, user, database) as conn:
        with conn.cursor() as cur:
            for table, expected in expected_counts.items():
                require(re.fullmatch(r"ers_[a-z0-9_]+", table) is not None,
                        f"invalid ERS table name in restore manifest: {table}")
                cur.execute(f'SELECT count(*) FROM "{table}"')
                actual = int(cur.fetchone()[0])
                require(actual == int(expected),
                        f"restored ERS row count mismatch: {table}")
                restored_counts[table] = actual

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
            require(boundaries == manifest["ers"]["case_boundaries"],
                    "restored ERS case boundaries mismatch")

            cur.execute(
                "SELECT availability, count(*) "
                "FROM ers_artifact_versions "
                "GROUP BY availability ORDER BY availability"
            )
            availability_counts = {
                str(availability): int(count)
                for availability, count in cur.fetchall()
            }
            require(
                availability_counts == manifest["ers"]["availability_counts"],
                "restored ERS artifact availability counts mismatch",
            )

            cur.execute(
                "SELECT object_sha256, byte_size, count(*) "
                "FROM ers_artifact_versions "
                "WHERE availability='available' "
                "GROUP BY object_sha256, byte_size "
                "ORDER BY object_sha256, byte_size"
            )
            db_objects = [
                {
                    "sha256": str(digest),
                    "bytes": int(byte_size),
                    "referenced_versions": int(refs),
                }
                for digest, byte_size, refs in cur.fetchall()
            ]

    expected_objects = [
        {
            "sha256": str(item["sha256"]),
            "bytes": int(item["bytes"]),
            "referenced_versions": int(item["referenced_versions"]),
        }
        for item in manifest["ers"]["object_set"]["files"]
    ]
    require(db_objects == expected_objects,
            "restored ERS DB/object-set references mismatch")

    verified = 0
    for item in manifest["ers"]["object_set"]["files"]:
        digest = str(item["sha256"])
        path = object_root / "sha256" / digest[:2] / digest
        require(path.is_file(), f"restored ERS object missing: {digest}")
        require(path.stat().st_size == int(item["bytes"]),
                f"restored ERS object byte size mismatch: {digest}")
        require(file_sha256(path) == digest,
                f"restored ERS object checksum mismatch: {digest}")
        verified += 1

    return {
        "table_counts": restored_counts,
        "case_count": len(boundaries),
        "case_boundaries_verified": True,
        "objects": verified,
        "object_bytes": sum(
            int(item["bytes"]) for item in manifest["ers"]["object_set"]["files"]
        ),
        "available_versions": int(manifest["ers"]["available_versions"]),
        "availability_counts": availability_counts,
        "availability_counts_verified": True,
        "object_references_verified": True,
    }


def restore_conn(port: int, user: str, database: str):
    return psycopg.connect(
        host="127.0.0.1", port=port, user=user, dbname=database,
        autocommit=False,
    )


def relocate_and_verify(
    *, port: int, user: str, database: str, objects: Path,
    manifest: dict[str, object],
) -> dict[str, int]:
    counts: dict[str, int] = {}
    with restore_conn(port, user, database) as conn:
        with conn.cursor() as cur:
            for table, expected in manifest["postgres"]["table_counts"].items():
                cur.execute(f"SELECT count(*) FROM {table}")
                actual = int(cur.fetchone()[0])
                require(actual == int(expected), f"restored row count mismatch: {table}")
                counts[table] = actual


            cur.execute("SELECT version_num FROM alembic_version")
            require(
                cur.fetchone()[0] == manifest["postgres"]["schema_version"],
                "restored schema version mismatch",
            )
            cur.execute(
                "SELECT version_id, content_sha256, byte_size "
                "FROM knowledge_document_versions ORDER BY version_id"
            )
            versions = cur.fetchall()
            require(
                len(versions) == int(manifest["knowledge"]["versions"]),
                "restored version count mismatch",
            )
            for _version_id, digest, byte_size in versions:
                path = objects / "sha256" / digest[:2] / digest
                require(path.is_file(), f"restored canonical object missing: {digest}")
                require(path.stat().st_size == int(byte_size),
                        f"restored canonical size mismatch: {digest}")
                require(file_sha256(path) == digest,
                        f"restored canonical checksum mismatch: {digest}")

            prefix = objects.resolve().as_uri().rstrip("/") + "/sha256/"
            cur.execute(
                "UPDATE knowledge_document_versions "
                "SET storage_uri = %s || left(content_sha256, 2) || '/' || content_sha256",
                (prefix,),
            )
            cur.execute(
                "UPDATE knowledge_index_jobs j SET state='pending', "
                "completed_at=NULL, last_error=NULL, updated_at=now() "
                "FROM knowledge_documents d "
                "WHERE j.document_id=d.document_id "
                "AND j.version_id=d.current_version_id "
                "AND j.state <> 'superseded'"
            )
            reset_jobs = cur.rowcount
            conn.commit()
    return {"reset_index_jobs": int(reset_jobs), **counts}


def qdrant_image() -> str:
    compose = (
        Path(__file__).resolve().parents[1] /
        "stage-j" / "docker-compose.qdrant.yml"
    )
    match = re.search(r"^\s*image:\s*(\S+)\s*$", compose.read_text(), re.MULTILINE)
    require(match is not None, "accepted Qdrant image unavailable")
    image = match.group(1)
    require("@sha256:" in image, "Qdrant image is not digest-pinned")
    return image


def start_qdrant(root: Path) -> tuple[str, str]:
    storage = root / "qdrant-storage"
    storage.mkdir(parents=True)
    name = f"stage-k-restore-qdrant-{os.getpid()}"
    port = free_port()
    run([
        "docker", "run", "-d",
        "--name", name,
        "--restart", "no",
        "--security-opt", "no-new-privileges:true",
        "-e", "QDRANT__TELEMETRY_DISABLED=true",
        "-p", f"127.0.0.1:{port}:6333",
        "-v", f"{storage}:/qdrant/storage",
        qdrant_image(),
    ], timeout=120)
    url = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        try:
            response = httpx.get(url + "/collections", timeout=2, trust_env=False)
            if response.status_code == 200:
                return name, url
        except Exception:
            pass
        time.sleep(0.5)
    raise RuntimeError("isolated Qdrant did not become ready")


def stop_qdrant(name: str | None) -> None:
    if not name:
        return
    try:
        run(["docker", "rm", "-f", name], timeout=60)
    except Exception:
        pass


def restore_env(
    *, port: int, user: str, database: str, objects: Path, qdrant_url: str,
) -> dict[str, str]:
    env = os.environ.copy()
    env.update({
        "PYTHONPATH": str(active_release() / "services/ai-bridge/src"),
        "AI_BRIDGE_DATABASE_URL": (
            f"postgresql+psycopg://{user}@127.0.0.1:{port}/{database}"
        ),
        "AI_BRIDGE_KNOWLEDGE_OBJECT_STORE_DIR": str(objects),
        "AI_BRIDGE_KNOWLEDGE_QDRANT_URL": qdrant_url,
        "AI_BRIDGE_GATEWAY_URL": "http://127.0.0.1:11435",
    })
    return env


def run_reindex(env: dict[str, str], manifest: dict[str, object]) -> dict[str, object]:
    script = Path(__file__).resolve().parents[1] / "stage-j3" / "reindex_pending.py"
    python = active_release() / "services/ai-bridge/.venv/bin/python"
    raw = run([
        str(python), str(script), "--limit", "1000", "--fail-fast",
    ], env=env, timeout=1800, cwd=Path(__file__).resolve().parents[2])
    decoder = json.JSONDecoder()
    values: list[object] = []
    index = 0
    while index < len(raw):
        while index < len(raw) and raw[index].isspace():
            index += 1
        if index >= len(raw):
            break
        value, index = decoder.raw_decode(raw, index)
        values.append(value)
    require(values and isinstance(values[-1], dict), "invalid reindex output")
    summary = values[-1].get("summary", {})
    require(summary.get("failed") == 0, "reindex reported failures")
    require(
        summary.get("completed") == int(manifest["knowledge"]["versions"]),
        "reindex did not rebuild every current document",
    )
    return summary


def qdrant_count(url: str, collection: str) -> int:
    response = httpx.get(
        f"{url}/collections/{collection}", timeout=10, trust_env=False
    )
    response.raise_for_status()
    return int(response.json()["result"]["points_count"])


def probe_restored_knowledge(
    *, env: dict[str, str], port: int, user: str, database: str,
) -> dict[str, object]:
    with restore_conn(port, user, database) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT s.domain, c.text "
                "FROM knowledge_chunks c "
                "JOIN knowledge_documents d ON d.current_version_id=c.version_id "
                "JOIN knowledge_sources s ON s.source_id=d.source_id "
                "ORDER BY c.chunk_id LIMIT 1"
            )
            row = cur.fetchone()
            require(row is not None, "restored knowledge has no current chunks")
            domain, chunk_text = row

    keys = (
        "AI_BRIDGE_DATABASE_URL",
        "AI_BRIDGE_KNOWLEDGE_OBJECT_STORE_DIR",
        "AI_BRIDGE_KNOWLEDGE_QDRANT_URL",
        "AI_BRIDGE_GATEWAY_URL",
    )
    previous = {key: os.environ.get(key) for key in keys}
    os.environ.update({key: env[key] for key in keys})
    source_dir = str(active_release() / "services/ai-bridge/src")
    if source_dir not in sys.path:
        sys.path.insert(0, source_dir)
    try:
        from ai_bridge.knowledge.rag import (
            build_rag_prompt,
            citation_payload,
            parse_rag_response,
            referenced_source_refs,
        )
        from ai_bridge.knowledge.runtime import KnowledgeRuntime
        from ai_bridge.platform.api import create_platform_app
        from ai_bridge.providers.contracts import KnowledgeQuery, LLMRequest
        from ai_bridge.providers.ollama import OllamaAdapter
        from ai_bridge.settings import Settings
        from fastapi.testclient import TestClient


        settings = Settings()
        query_text = " ".join(str(chunk_text).split())[:600]
        query = KnowledgeQuery(
            request_id="stage-k-restore-search",
            domain=str(domain),
            query=query_text,
            mode="hybrid",
            limit=8,
            context={"recovery_validation": True},
        )
        with KnowledgeRuntime(settings) as runtime:
            retrieval = runtime.search(query)
        require(retrieval.results, "restored Knowledge Search returned no results")

        prompt = build_rag_prompt(
            question=(
                "Podaj jeden konkretny fakt techniczny wynikający wyłącznie "
                "z dostarczonych fragmentów."
            ),
            results=retrieval.results,
            max_sources=settings.knowledge_rag_max_sources,
            max_context_chars=settings.knowledge_rag_context_max_chars,
        )
        provider = OllamaAdapter.from_endpoint(
            base_url=settings.gateway_url,
            default_model=settings.ollama_model,
            timeout_seconds=300,
            request_source="stage-k-restore-validation",
            request_priority=settings.gateway_priority_interactive,
            node_id=settings.node_id,
        )
        generated = provider.generate(LLMRequest(
            request_id="stage-k-restore-rag",
            capability="structured-generation",
            messages=prompt.messages,
            response_schema=prompt.response_schema,
            temperature=0,
            reasoning_enabled=False,
            context={"domain": str(domain), "recovery_validation": True},
        ))
        parsed = parse_rag_response(generated.content, prompt)
        require(parsed.claims, "restored RAG returned no grounded claims")
        refs = referenced_source_refs(parsed)
        citations = citation_payload(prompt, refs)
        require(citations, "restored RAG returned no citations")


        document_id = citations[0]["document_id"]
        require(bool(document_id), "citation missing document_id")

        class AllowPolicy:
            async def authorize(self, request):
                return None

        app = create_platform_app(
            object(),
            settings,
            policy=AllowPolicy(),
            knowledge_runtime_factory=lambda: KnowledgeRuntime(settings),
        )
        with TestClient(app) as client:
            search_response = client.post("/knowledge/search", json={
                "schema_version": 1,
                "context": {"domain": str(domain)},
                "query": query_text,
                "mode": "hybrid",
                "limit": 5,
            })
            require(search_response.status_code == 200,
                    "restored Platform Knowledge Search failed")
            require(search_response.json()["results"],
                    "restored Platform Knowledge Search returned no results")
            metadata_response = client.get(
                f"/knowledge/documents/{document_id}"
            )
            require(metadata_response.status_code == 200,
                    "restored source metadata opening failed")
            content_response = client.get(
                f"/knowledge/documents/{document_id}/content"
            )
            require(content_response.status_code == 200,
                    "restored source content opening failed")

        expected_hash = metadata_response.json()["version"]["content_sha256"]
        import hashlib
        actual_hash = hashlib.sha256(content_response.content).hexdigest()
        require(actual_hash == expected_hash,
                "opened restored source checksum mismatch")
        return {
            "search_results": len(retrieval.results),
            "search_backend": retrieval.backend,
            "rag_claims": len(parsed.claims),
            "rag_citations": len(citations),
            "opened_document_id": document_id,
            "opened_content_sha256": actual_hash,
            "llm_model": generated.execution.model,
        }
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def production_qdrant_points() -> int | None:
    try:
        response = httpx.get(
            "http://127.0.0.1:6333/collections/knowledge_dense_bge_m3_1024_v1",
            timeout=3,
            trust_env=False,
        )
        if response.status_code == 200:
            return int(response.json()["result"]["points_count"])
    except Exception:
        return None
    return None




def validate(backup: Path, ers_backup: Path | None = None) -> Path:
    backup = backup.resolve()
    offline = verify_backup(backup)
    manifest = json.loads((backup / "manifest.json").read_text())
    ers_manifest = None
    ers_offline = None
    has_ers_tables = any(
        str(name).startswith("ers_")
        for name in manifest["postgres"]["table_counts"]
    )
    require(
        not has_ers_tables or ers_backup is not None,
        "ERS Case Store manifest is required for restore of an ERS-active backup",
    )
    if ers_backup is not None:
        ers_backup = ers_backup.resolve()
        ers_offline = verify_backup(ers_backup)
        ers_manifest = json.loads((ers_backup / "manifest.json").read_text())
        require(ers_manifest["domain"] == "ERSCaseStore",
                "optional ERS manifest has wrong domain")
        require(ers_manifest["backup_id"] == manifest["backup_id"],
                "Knowledge/ERS backup IDs differ")
        require(
            ers_manifest["postgres"]["dump"]["sha256"]
            == manifest["postgres"]["dump"]["sha256"],
            "Knowledge/ERS PostgreSQL dump checksum differs",
        )
        require(
            ers_manifest["postgres"]["dump"]["path"]
            == manifest["postgres"]["dump"]["path"],
            "Knowledge/ERS PostgreSQL dump path differs",
        )
        for table, expected in ers_manifest["postgres"]["domain_table_counts"].items():
            require(
                int(manifest["postgres"]["table_counts"].get(table, -1))
                == int(expected),
                f"Knowledge/ERS table count differs: {table}",
            )
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    evidence = RESTORE_ROOT / f"{manifest['backup_id']}-{stamp}-{os.getpid()}"
    evidence.mkdir(parents=True, mode=0o700)
    atomic_text(evidence / "source-backup.txt", str(backup) + "\n")
    if ers_backup is not None:
        atomic_text(evidence / "source-ers-backup.txt", str(ers_backup) + "\n")

    qdrant_name: str | None = None
    pgdata: str | None = None
    started = time.monotonic()
    prod_qdrant_before = production_qdrant_points()
    try:
        port, user, pgdata = start_postgres(evidence)
        database = restore_database(backup, manifest, port, user)
        objects = restore_objects(backup, evidence, manifest)
        restored = relocate_and_verify(
            port=port, user=user, database=database,
            objects=objects, manifest=manifest,
        )
        require(restored["reset_index_jobs"] > 0,
                "restore recovery transform reset no index jobs")

        ers_restore = None
        if ers_manifest is not None and ers_backup is not None:
            ers_objects = restore_ers_objects(
                ers_backup, evidence, ers_manifest
            )
            ers_restore = verify_restored_ers(
                port=port,
                user=user,
                database=database,
                object_root=ers_objects,
                manifest=ers_manifest,
            )

        qdrant_name, qdrant_url = start_qdrant(evidence)
        empty = httpx.get(
            qdrant_url + "/collections", timeout=5, trust_env=False
        ).json()["result"]["collections"]
        require(empty == [], "isolated Qdrant was not empty before reindex")

        env = restore_env(
            port=port, user=user, database=database,
            objects=objects, qdrant_url=qdrant_url,
        )
        reindex = run_reindex(env, manifest)
        collection = str(reindex["collection"])
        points = qdrant_count(qdrant_url, collection)
        require(
            points == int(manifest["knowledge"]["current_chunks"]),
            "rebuilt Qdrant point count mismatch",
        )
        probe = probe_restored_knowledge(
            env=env, port=port, user=user, database=database
        )
        prod_qdrant_after = production_qdrant_points()
        require(
            prod_qdrant_before == prod_qdrant_after,
            "production Qdrant changed during isolated restore validation",
        )

        result = {
            "status": "PASS",
            "backup_id": manifest["backup_id"],
            "backup_set": str(backup),
            "evidence_dir": str(evidence),
            "duration_seconds": round(time.monotonic() - started, 3),
            "offline_verification": offline,
            "postgres": {
                "isolated": True,
                "port": port,
                "database": database,
                "schema_version": manifest["postgres"]["schema_version"],
                "restored_counts": restored,
            },
            "canonical": {
                "isolated_root": str(objects),
                "objects": manifest["knowledge"]["canonical"]["objects"],
                "bytes": manifest["knowledge"]["canonical"]["bytes"],
                "storage_uri_relocated": True,
            },
            "qdrant": {
                "isolated": True,
                "started_empty": True,
                "url": qdrant_url,
                "collection": collection,
                "points": points,
                "source_snapshot_used": False,
                "production_points_before": prod_qdrant_before,
                "production_points_after": prod_qdrant_after,
                "reindex": reindex,
            },
            "knowledge_probe": probe,
            "ers": (
                {
                    "offline_verification": ers_offline,
                    "restore": ers_restore,
                    "object_store_root": (
                        str(evidence / "ers-object-store")
                        if ers_restore is not None
                        else None
                    ),
                }
                if ers_manifest is not None
                else None
            ),
        }
        atomic_text(
            evidence / "result.json",
            json.dumps(result, indent=2, sort_keys=True) + "\n",
        )
        atomic_text(evidence / "PASS", manifest["backup_id"] + "\n")
        print(json.dumps({
            "status": "PASS",
            "backup_id": manifest["backup_id"],
            "evidence": str(evidence),
            "duration_seconds": result["duration_seconds"],
            "qdrant_points": points,
            "rag_claims": probe["rag_claims"],
            "rag_citations": probe["rag_citations"],
            "ers_cases": (
                ers_restore["case_count"]
                if ers_restore is not None
                else None
            ),
            "ers_objects": (
                ers_restore["objects"]
                if ers_restore is not None
                else None
            ),
        }, sort_keys=True))
        return evidence
    except Exception as exc:
        failure = {
            "status": "FAIL",
            "backup_id": manifest.get("backup_id"),
            "backup_set": str(backup),
            "evidence_dir": str(evidence),
            "duration_seconds": round(time.monotonic() - started, 3),
            "error_type": type(exc).__name__,
            "error": str(exc),
        }
        atomic_text(
            evidence / "FAIL.json",
            json.dumps(failure, indent=2, sort_keys=True) + "\n",
        )
        raise
    finally:
        stop_qdrant(qdrant_name)
        if pgdata is not None:
            stop_postgres(pgdata)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("backup_set", type=Path)
    parser.add_argument(
        "--ers",
        type=Path,
        help="optional matching ERS Case Store manifest set",
    )
    args = parser.parse_args()
    validate(args.backup_set, args.ers)


if __name__ == "__main__":
    main()
