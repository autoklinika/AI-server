#!/usr/bin/env python3
"""Fail-closed Stage J production data preparation.

Runs before release build: one immutable PostgreSQL backup, two-pass PDF ingest,
Qdrant reindex drain, and content-addressed object integrity verification.
Secrets are read from the active AI Bridge process and are never printed.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import pwd
import re
import subprocess
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[2]
BASE = Path("/opt/ai-platform/releases/stage-i-30626dcc60f8")
PYTHON = BASE / "services/ai-bridge/.venv/bin/python"
BACKUP_ROOT = Path("/srv/ai-data/backups/stage-j")
OBJECT_ROOT = Path("/srv/ai-data/knowledge/canonical/objects")
CURRENT = Path("/opt/ai-platform/current")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def run(args: list[str], *, env: dict[str, str] | None = None,
        timeout: int = 60, cwd: Path | None = None,
        preexec_fn=None) -> str:
    result = subprocess.run(
        [str(item) for item in args],
        check=False,
        capture_output=True,
        text=True,
        env=env,
        timeout=timeout,
        cwd=str(cwd) if cwd else None,
        preexec_fn=preexec_fn,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"command failed rc={result.returncode}: {Path(str(args[0])).name}"
        )
    return result.stdout


def active_database_url() -> str:
    pid = run([
        "systemctl", "show", "ai-bridge.service",
        "-p", "MainPID", "--value",
    ]).strip()
    require(pid.isdigit() and int(pid) > 0, "AI Bridge MainPID unavailable")
    entries = Path(f"/proc/{pid}/environ").read_bytes().split(b"\0")
    values = [
        item.split(b"=", 1)[1].decode()
        for item in entries
        if item.startswith(b"AI_BRIDGE_DATABASE_URL=")
    ]
    require(len(values) == 1, "production database URL unavailable")
    return values[0]


def postgres_env(database_url: str) -> dict[str, str]:
    normalized = database_url.replace(
        "postgresql+psycopg://", "postgresql://", 1
    )
    parsed = urlsplit(normalized)
    require(parsed.scheme in {"postgresql", "postgres"}, "unexpected DB scheme")
    require(bool(parsed.hostname and parsed.username and parsed.path), "incomplete DB URL")
    env = {
        "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
        "LANG": "C.UTF-8",
        "PGHOST": parsed.hostname or "",
        "PGPORT": str(parsed.port or 5432),
        "PGUSER": unquote(parsed.username or ""),
        "PGPASSWORD": unquote(parsed.password or ""),
        "PGDATABASE": parsed.path.lstrip("/"),
    }
    return env


def file_digest(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_text(path: Path, text: str, mode: int = 0o600) -> None:
    tmp = path.with_name(path.name + f".tmp-{os.getpid()}")
    tmp.write_text(text)
    os.chmod(tmp, mode)
    os.replace(tmp, path)


def ensure_backup(database_url: str, source_sha: str) -> dict[str, object]:
    directory = BACKUP_ROOT / source_sha
    directory.mkdir(parents=True, exist_ok=True)
    os.chmod(directory, 0o700)
    backup = directory / "pre-ingest.dump"
    checksum = directory / "pre-ingest.dump.sha256"

    if not backup.exists():
        tmp = directory / f".pre-ingest.dump.tmp-{os.getpid()}"
        if tmp.exists():
            tmp.unlink()
        run(
            ["pg_dump", "--format=custom", f"--file={tmp}"],
            env=postgres_env(database_url),
            timeout=600,
        )
        require(tmp.is_file() and tmp.stat().st_size > 0, "empty PostgreSQL backup")
        run(["pg_restore", "-l", str(tmp)], timeout=120)
        os.chmod(tmp, 0o600)
        os.replace(tmp, backup)

    run(["pg_restore", "-l", str(backup)], timeout=120)
    digest = file_digest(backup)
    if checksum.exists():
        require(checksum.read_text().strip() == digest, "backup checksum drift")
    else:
        atomic_text(checksum, digest + "\n")
    return {
        "path": str(backup),
        "sha256": digest,
        "bytes": backup.stat().st_size,
    }


def worker_identity():
    info = OBJECT_ROOT.parent.stat()
    account = pwd.getpwuid(info.st_uid)
    return account, info.st_gid


def demote(account, gid):
    def apply() -> None:
        os.initgroups(account.pw_name, gid)
        os.setgid(gid)
        os.setuid(account.pw_uid)
    return apply


def worker_env(database_url: str, account) -> dict[str, str]:
    return {
        "HOME": account.pw_dir,
        "USER": account.pw_name,
        "LOGNAME": account.pw_name,
        "LANG": "C.UTF-8",
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "PYTHONPATH": str(ROOT / "src"),
        "AI_BRIDGE_DATABASE_URL": database_url,
    }


def parse_json_stream(raw: str) -> list[object]:
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
    return values


def run_worker(args: list[str], database_url: str, *, timeout: int) -> list[object]:
    account, gid = worker_identity()
    raw = run(
        [str(PYTHON), *args],
        env=worker_env(database_url, account),
        timeout=timeout,
        cwd=ROOT,
        preexec_fn=demote(account, gid),
    )
    return parse_json_stream(raw)


def prepare_knowledge(database_url: str) -> dict[str, object]:
    ingest = str(ROOT / "deploy/stage-j4/ingest_ecu_pdfs.py")
    reindex = str(ROOT / "deploy/stage-j3/reindex_pending.py")

    dry_values = run_worker([ingest, "--dry-run"], database_url, timeout=120)
    require(len(dry_values) == 1, "unexpected PDF dry-run output")
    dry = dry_values[0]
    require(isinstance(dry, dict) and dry.get("mode") == "dry-run", "invalid PDF dry-run")
    expected = int(dry["documents"])
    require(expected > 0, "no PDF documents selected")

    first_values = run_worker([ingest], database_url, timeout=1800)
    first = first_values[-1]["summary"]
    require(first["documents"] == expected, "first PDF ingest document count mismatch")

    second_values = run_worker([ingest], database_url, timeout=1800)
    second = second_values[-1]["summary"]
    require(second["documents"] == expected, "second PDF ingest document count mismatch")
    require(second["new_versions"] == 0, "PDF ingest is not version-idempotent")
    require(second["new_chunks"] == 0, "PDF ingest is not chunk-idempotent")

    passes: list[dict[str, object]] = []
    for _ in range(5):
        values = run_worker(
            [reindex, "--limit", "1000", "--fail-fast"],
            database_url,
            timeout=1800,
        )
        summary = values[-1]["summary"]
        require(summary["failed"] == 0, "knowledge reindex failure")
        passes.append(summary)
        if summary["selected"] == 0:
            break
    require(passes[-1]["selected"] == 0, "pending knowledge index jobs remain")
    return {
        "documents": expected,
        "first_ingest": first,
        "second_ingest": second,
        "reindex_passes": passes,
    }


def verify_objects(source_sha: str) -> dict[str, object]:
    root = OBJECT_ROOT / "sha256"
    require(root.is_dir(), "canonical object store missing")
    rows: list[str] = []
    total_bytes = 0
    files = sorted(path for path in root.glob("*/*") if path.is_file())
    require(bool(files), "canonical object store is empty")
    for path in files:
        expected = path.name
        require(re.fullmatch(r"[0-9a-f]{64}", expected) is not None, "invalid object name")
        require(path.parent.name == expected[:2], "invalid content-addressed path")
        actual = file_digest(path)
        require(actual == expected, "canonical object checksum mismatch")
        size = path.stat().st_size
        total_bytes += size
        rows.append(f"{actual} {size} {path.relative_to(OBJECT_ROOT).as_posix()}")

    directory = BACKUP_ROOT / source_sha
    directory.mkdir(parents=True, exist_ok=True)
    os.chmod(directory, 0o700)
    manifest = directory / "canonical-objects.sha256"
    payload = "\n".join(rows) + "\n"
    atomic_text(manifest, payload)
    return {
        "objects": len(files),
        "bytes": total_bytes,
        "manifest": str(manifest),
        "manifest_sha256": sha256(payload.encode()).hexdigest(),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-sha", required=True)
    args = parser.parse_args()
    require(re.fullmatch(r"[0-9a-f]{40}", args.source_sha) is not None, "invalid source SHA")
    require(os.geteuid() == 0, "Stage J data preparation requires root executor")
    require(CURRENT.resolve(strict=True) == BASE, "Stage I must remain active during data prep")
    require(PYTHON.is_file(), "accepted Stage I Python runtime missing")

    database_url = active_database_url()
    backup = ensure_backup(database_url, args.source_sha)
    knowledge = prepare_knowledge(database_url)
    integrity = verify_objects(args.source_sha)
    result = {
        "status": "PASS",
        "source_sha": args.source_sha,
        "backup": backup,
        "knowledge": knowledge,
        "integrity": integrity,
    }
    record = BACKUP_ROOT / args.source_sha / "data-prepare.json"
    atomic_text(record, json.dumps(result, sort_keys=True, indent=2) + "\n")
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
