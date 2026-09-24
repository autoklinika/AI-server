#!/usr/bin/env python3
"""Stage K K3 backup/verify/restore for ERS, Hermes durable state and host config."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import sqlite3
import stat
import tarfile
import tempfile
import time

from backup import verify_target
from common import atomic_text, file_sha256, git_head, machine_identity_hash, require

ERS_ROOT = Path("/srv/ai-data/knowledge/source-cache/EcuRepairService")
HERMES_ROOT = Path("/srv/ai-data/hermes")
EVIDENCE_ROOT = Path("/srv/ai-data/backups/stage-k/k3-restore-validation")

ERS_EXCLUDE_DIRS = {".git", ".venv", "__pycache__", ".pytest_cache"}
SECRET_BASENAMES = {
    ".env", "auth.json", "id_rsa", "id_ed25519", "globalnas.credentials",
}
SECRET_SUFFIXES = {".pem", ".key", ".p12", ".pfx"}

HERMES_SQLITE = {
    "state.db": HERMES_ROOT / "state.db",
    "kanban.db": HERMES_ROOT / "kanban.db",
    "response_store.db": HERMES_ROOT / "response_store.db",
    "runs_idempotency.db": HERMES_ROOT / "runs_idempotency.db",
    "cron-executions.db": HERMES_ROOT / "cron" / "executions.db",
}

HERMES_DURABLE_PATHS = (
    "config.yaml",
    "SOUL.md",
    "channel_directory.json",
    "install_id",
    "context_length_cache.yaml",
    "memories",
    "skills",
    "pending_messages",
    "hooks",
    "plugins",
    "scripts",
    "platforms",
    "gateway",
    "sessions/sessions.json",
    "gateway_state.json",
    "gateway_voice_mode.json",
)

PLATFORM_CONFIG_PATHS = (
    "/etc/fstab",
    "/etc/systemd/system/ai-bridge.service",
    "/etc/systemd/system/ai-bridge.service.d/zz-lan-only.conf",
    "/etc/systemd/system/ai-gateway.service",
    "/etc/systemd/system/ai-gateway.service.d/96-gpu-residency.conf",
    "/etc/systemd/system/ai-bridge-analysis.service",
    "/etc/systemd/system/ai-bridge-analysis.timer",
    "/etc/systemd/system/comfyui.service",
    "/etc/systemd/system/comfyui.service.d/zz-localhost-only.conf",
    "/etc/systemd/system/ollama-preload.service",
    "/etc/systemd/system/ollama.service",
    "/etc/systemd/system/ollama.service.d/override.conf",
    "/etc/systemd/system/ollama.service.d/resident.conf",
    "/etc/systemd/system/ollama.service.d/vulkan.conf",
    "/etc/systemd/system/ollama.service.d/zz-localhost-only.conf",
    "/home/harrypotter/.config/systemd/user/hermes-gateway.service",
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def is_secret_like(path: Path) -> bool:
    name = path.name.lower()
    return name in SECRET_BASENAMES or path.suffix.lower() in SECRET_SUFFIXES


def collect_tree_files(root: Path) -> list[Path]:
    require(root.is_dir(), f"source directory missing: {root}")
    files: list[Path] = []
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root)
        if any(part in ERS_EXCLUDE_DIRS for part in rel.parts):
            continue
        if path.is_symlink():
            raise RuntimeError(f"symlink not allowed in K3 snapshot: {path}")
        if not path.is_file():
            continue
        if is_secret_like(path):
            continue
        files.append(path)
    return files


def collect_selected_files(root: Path, selected: tuple[str, ...]) -> list[Path]:
    files: list[Path] = []
    for rel_text in selected:
        path = root / rel_text
        if not path.exists():
            continue
        if path.is_symlink():
            raise RuntimeError(f"symlink not allowed in K3 snapshot: {path}")
        if path.is_file():
            if not is_secret_like(path):
                files.append(path)
            continue
        for item in sorted(path.rglob("*")):
            if item.is_symlink():
                raise RuntimeError(f"symlink not allowed in K3 snapshot: {item}")
            if item.is_file() and not item.name.endswith(".lock") and not is_secret_like(item):
                if "__pycache__" not in item.parts and item.suffix != ".pyc":
                    files.append(item)
    return sorted(set(files))


def create_tar(archive: Path, base: Path, files: list[Path], prefix: str) -> None:
    archive.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive, "w:gz", compresslevel=6) as tf:
        for source in files:
            rel = source.relative_to(base).as_posix()
            tf.add(source, arcname=f"{prefix}/{rel}", recursive=False)


def manifest_from_tar(archive: Path, prefix: str) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    with tarfile.open(archive, "r:gz") as tf:
        for member in sorted(tf.getmembers(), key=lambda x: x.name):
            require(member.isfile(), f"unexpected non-file tar member: {member.name}")
            expected_prefix = prefix.rstrip("/") + "/"
            require(member.name.startswith(expected_prefix), "tar prefix mismatch")
            rel = member.name[len(expected_prefix):]
            require(rel and not rel.startswith("/") and ".." not in Path(rel).parts,
                    "unsafe tar member path")
            stream = tf.extractfile(member)
            require(stream is not None, f"cannot read tar member: {member.name}")
            digest = hashlib.sha256()
            while True:
                block = stream.read(1024 * 1024)
                if not block:
                    break
                digest.update(block)
            rows.append({
                "path": rel,
                "bytes": int(member.size),
                "sha256": digest.hexdigest(),
                "mode": oct(stat.S_IMODE(member.mode)),
            })
    return rows


def sqlite_backup(source: Path, destination: Path) -> dict[str, object]:
    """Create a consistent SQLite backup locally, then publish the frozen file."""
    require(source.is_file(), f"SQLite source missing: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="stage-k-k3-sqlite-") as tmpdir:
        local = Path(tmpdir) / source.name
        src = sqlite3.connect(f"file:{source}?mode=ro", uri=True, timeout=30)
        dst = sqlite3.connect(local)
        try:
            src.backup(dst, pages=256, sleep=0.05)
            result = dst.execute("PRAGMA quick_check").fetchone()[0]
            require(result == "ok", f"SQLite backup quick_check failed: {source.name}")
            tables = [
                row[0] for row in dst.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
                )
            ]
        finally:
            dst.close()
            src.close()
        local_hash = file_sha256(local)
        shutil.copy2(local, destination)
        require(destination.stat().st_size == local.stat().st_size,
                f"published SQLite size mismatch: {source.name}")
        require(file_sha256(destination) == local_hash,
                f"published SQLite checksum mismatch: {source.name}")
    return {
        "path": destination.name,
        "bytes": destination.stat().st_size,
        "sha256": file_sha256(destination),
        "quick_check": "ok",
        "tables": tables,
    }


def source_identity() -> dict[str, object]:
    return {
        "hostname": socket.gethostname(),
        "machine_id_sha256": machine_identity_hash(),
        "stage_k_code_git_sha": git_head(),
    }


def write_manifest_set(directory: Path, manifest: dict[str, object]) -> None:
    directory.mkdir(parents=True, exist_ok=False)
    manifest_path = directory / "manifest.json"
    atomic_text(manifest_path, json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    atomic_text(
        directory / "manifest.sha256",
        file_sha256(manifest_path) + "  manifest.json\n",
    )
    atomic_text(directory / "COMPLETE", str(manifest["backup_id"]) + "\n")


def publish(source: Path, destination: Path) -> None:
    require(not destination.exists(), f"destination already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    os.replace(source, destination)


def create_backup(target_root: Path, tier: str, allow_local: bool) -> dict[str, object]:
    root = target_root.resolve()
    require(root.name == "AI_Platform", "target root must be AI_Platform")
    target = verify_target(root, allow_local)
    backup_id = utc_now().strftime("%Y%m%dT%H%M%SZ")
    started = utc_now()

    staging = root / ".incomplete" / f"k3-{backup_id}.{os.getpid()}"
    staging.mkdir(parents=True, mode=0o700)
    ers_stage = staging / "ers"
    hermes_stage = staging / "hermes"
    platform_stage = staging / "platform"
    ers_stage.mkdir()
    hermes_stage.mkdir()
    platform_stage.mkdir()

    ers_files = collect_tree_files(ERS_ROOT)
    ers_archive = ers_stage / "ers.tar.gz"
    create_tar(ers_archive, ERS_ROOT, ers_files, "tree")
    ers_rows = manifest_from_tar(ers_archive, "tree")

    hermes_files = collect_selected_files(HERMES_ROOT, HERMES_DURABLE_PATHS)
    hermes_archive = hermes_stage / "files.tar.gz"
    create_tar(hermes_archive, HERMES_ROOT, hermes_files, "hermes")
    hermes_rows = manifest_from_tar(hermes_archive, "hermes")

    sqlite_dir = hermes_stage / "sqlite"
    sqlite_rows: dict[str, object] = {}
    for name, source in HERMES_SQLITE.items():
        sqlite_rows[name] = sqlite_backup(source, sqlite_dir / name)

    platform_sources = [Path(p) for p in PLATFORM_CONFIG_PATHS if Path(p).is_file()]
    for path in platform_sources:
        require(not is_secret_like(path), f"secret-like platform config refused: {path}")
    platform_archive = platform_stage / "config.tar.gz"
    create_tar(platform_archive, Path("/"), platform_sources, "rootfs")
    platform_rows = manifest_from_tar(platform_archive, "rootfs")

    ers_snapshot = root / "ERS" / "snapshots" / tier / backup_id
    hermes_snapshot = root / "Hermes" / "snapshots" / tier / backup_id
    platform_snapshot = root / "Platform" / "config" / "snapshots" / tier / backup_id
    publish(ers_stage, ers_snapshot)
    publish(hermes_stage, hermes_snapshot)
    publish(platform_stage, platform_snapshot)

    identity = source_identity()
    completed = utc_now().isoformat()
    ers_manifest = {
        "manifest_schema_version": 1,
        "status": "COMPLETE",
        "domain": "ERS",
        "backup_id": backup_id,
        "tier": tier,
        "created_at": started.isoformat(),
        "completed_at": completed,
        "target": target,
        "source": identity,
        "source_root": str(ERS_ROOT),
        "snapshot": {
            "archive_path": (ers_snapshot / "ers.tar.gz").relative_to(root).as_posix(),
            "bytes": (ers_snapshot / "ers.tar.gz").stat().st_size,
            "sha256": file_sha256(ers_snapshot / "ers.tar.gz"),
        },
        "files": ers_rows,
        "excluded": sorted(ERS_EXCLUDE_DIRS),
        "secrets_included": False,
    }
    hermes_manifest = {
        "manifest_schema_version": 1,
        "status": "COMPLETE",
        "domain": "Hermes",
        "backup_id": backup_id,
        "tier": tier,
        "created_at": started.isoformat(),
        "completed_at": completed,
        "target": target,
        "source": identity,
        "source_root": str(HERMES_ROOT),
        "snapshot": {
            "archive_path": (hermes_snapshot / "files.tar.gz").relative_to(root).as_posix(),
            "bytes": (hermes_snapshot / "files.tar.gz").stat().st_size,
            "sha256": file_sha256(hermes_snapshot / "files.tar.gz"),
        },
        "files": hermes_rows,
        "sqlite": {
            name: {
                **meta,
                "path": (hermes_snapshot / "sqlite" / name).relative_to(root).as_posix(),
            }
            for name, meta in sqlite_rows.items()
        },
        "secrets_included": False,
    }
    platform_manifest = {
        "manifest_schema_version": 1,
        "status": "COMPLETE",
        "domain": "PlatformConfig",
        "backup_id": backup_id,
        "tier": tier,
        "created_at": started.isoformat(),
        "completed_at": completed,
        "target": target,
        "source": identity,
        "snapshot": {
            "archive_path": (platform_snapshot / "config.tar.gz").relative_to(root).as_posix(),
            "bytes": (platform_snapshot / "config.tar.gz").stat().st_size,
            "sha256": file_sha256(platform_snapshot / "config.tar.gz"),
        },
        "files": platform_rows,
        "secrets_included": False,
        "secrets_bundle_required_for_full_recovery": True,
    }

    ers_manifest_dir = root / "ERS" / "manifests" / tier / backup_id
    hermes_manifest_dir = root / "Hermes" / "manifests" / tier / backup_id
    platform_manifest_dir = root / "Platform" / "manifests" / tier / backup_id
    write_manifest_set(ers_manifest_dir, ers_manifest)
    write_manifest_set(hermes_manifest_dir, hermes_manifest)
    write_manifest_set(platform_manifest_dir, platform_manifest)

    try:
        staging.rmdir()
        staging.parent.rmdir()
    except OSError:
        pass

    return {
        "status": "PASS",
        "backup_id": backup_id,
        "ers_manifest": str(ers_manifest_dir),
        "hermes_manifest": str(hermes_manifest_dir),
        "platform_manifest": str(platform_manifest_dir),
    }


def platform_root(path: Path) -> Path:
    path = path.resolve()
    for candidate in (path, *path.parents):
        if candidate.name == "AI_Platform":
            return candidate
    raise RuntimeError("manifest is not below AI_Platform")
def resolve_ref(manifest_dir: Path, relative: str) -> Path:
    root = platform_root(manifest_dir)
    path = (root / relative).resolve()
    require(path == root or root in path.parents, "manifest reference escapes AI_Platform")
    return path


def load_verified_manifest(manifest_dir: Path) -> dict[str, object]:
    manifest_dir = manifest_dir.resolve()
    complete = manifest_dir / "COMPLETE"
    manifest_path = manifest_dir / "manifest.json"
    checksum_path = manifest_dir / "manifest.sha256"
    require(complete.is_file(), "COMPLETE marker missing")
    require(manifest_path.is_file(), "manifest.json missing")
    require(checksum_path.is_file(), "manifest.sha256 missing")
    expected = checksum_path.read_text().split()[0]
    require(file_sha256(manifest_path) == expected, "manifest checksum mismatch")
    manifest = json.loads(manifest_path.read_text())
    require(manifest.get("status") == "COMPLETE", "manifest status is not COMPLETE")
    require(complete.read_text().strip() == manifest.get("backup_id"),
            "COMPLETE marker mismatch")
    require(manifest.get("secrets_included") is False,
            "plaintext K3 manifest unexpectedly includes secrets")
    snapshot = manifest["snapshot"]
    archive = resolve_ref(manifest_dir, snapshot["archive_path"])
    require(archive.is_file(), "snapshot archive missing")
    require(archive.stat().st_size == int(snapshot["bytes"]), "snapshot size mismatch")
    require(file_sha256(archive) == snapshot["sha256"], "snapshot checksum mismatch")
    if manifest["domain"] == "Hermes":
        for name, meta in manifest["sqlite"].items():
            db = resolve_ref(manifest_dir, meta["path"])
            require(db.is_file(), f"Hermes SQLite backup missing: {name}")
            require(db.stat().st_size == int(meta["bytes"]), f"SQLite size mismatch: {name}")
            require(file_sha256(db) == meta["sha256"], f"SQLite checksum mismatch: {name}")
            con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
            try:
                require(con.execute("PRAGMA quick_check").fetchone()[0] == "ok",
                        f"SQLite quick_check failed: {name}")
            finally:
                con.close()
    return manifest


def verify(manifest_dir: Path) -> dict[str, object]:
    manifest = load_verified_manifest(manifest_dir)
    result = {
        "status": "PASS",
        "domain": manifest["domain"],
        "backup_id": manifest["backup_id"],
        "files": len(manifest["files"]),
        "snapshot_bytes": manifest["snapshot"]["bytes"],
    }
    if manifest["domain"] == "Hermes":
        result["sqlite_databases"] = len(manifest["sqlite"])
    return result


def safe_extract(archive: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive, "r:gz") as tf:
        members = tf.getmembers()
        for member in members:
            require(member.isfile(), f"unsafe tar member type: {member.name}")
            rel = Path(member.name)
            require(not rel.is_absolute() and ".." not in rel.parts,
                    f"unsafe tar member path: {member.name}")
        tf.extractall(destination, members=members, filter="data")


def validate_files(base: Path, prefix: str, rows: list[dict[str, object]]) -> None:
    for row in rows:
        path = base / prefix / str(row["path"])
        require(path.is_file(), f"restored file missing: {row['path']}")
        require(path.stat().st_size == int(row["bytes"]),
                f"restored file size mismatch: {row['path']}")
        require(file_sha256(path) == row["sha256"],
                f"restored file checksum mismatch: {row['path']}")


def restore_validate(
    ers_dir: Path, hermes_dir: Path, platform_dir: Path
) -> dict[str, object]:
    manifests = {
        "ERS": load_verified_manifest(ers_dir),
        "Hermes": load_verified_manifest(hermes_dir),
        "PlatformConfig": load_verified_manifest(platform_dir),
    }
    backup_ids = {str(m["backup_id"]) for m in manifests.values()}
    require(len(backup_ids) == 1, "K3 manifests do not share one backup_id")
    backup_id = backup_ids.pop()
    stamp = utc_now().strftime("%Y%m%dT%H%M%SZ")
    evidence = EVIDENCE_ROOT / f"{backup_id}-{stamp}-{os.getpid()}"
    evidence.mkdir(parents=True, mode=0o700)
    started = time.monotonic()

    for domain, manifest_dir, prefix in (
        ("ERS", ers_dir, "tree"),
        ("Hermes", hermes_dir, "hermes"),
        ("PlatformConfig", platform_dir, "rootfs"),
    ):
        manifest = manifests[domain]
        archive = resolve_ref(manifest_dir, manifest["snapshot"]["archive_path"])
        domain_root = evidence / domain
        safe_extract(archive, domain_root)
        validate_files(domain_root, prefix, manifest["files"])

    sqlite_results: dict[str, str] = {}
    hermes_manifest = manifests["Hermes"]
    sqlite_target = evidence / "Hermes" / "sqlite"
    sqlite_target.mkdir(parents=True, exist_ok=True)
    for name, meta in hermes_manifest["sqlite"].items():
        source = resolve_ref(hermes_dir, meta["path"])
        target = sqlite_target / name
        shutil.copy2(source, target)
        require(file_sha256(target) == meta["sha256"], f"restored SQLite hash mismatch: {name}")
        con = sqlite3.connect(target)
        try:
            result = con.execute("PRAGMA quick_check").fetchone()[0]
            require(result == "ok", f"restored SQLite quick_check failed: {name}")
            sqlite_results[name] = result
        finally:
            con.close()

    result = {
        "status": "PASS",
        "backup_id": backup_id,
        "duration_seconds": round(time.monotonic() - started, 3),
        "evidence_dir": str(evidence),
        "ers_files": len(manifests["ERS"]["files"]),
        "hermes_files": len(manifests["Hermes"]["files"]),
        "hermes_sqlite": sqlite_results,
        "platform_config_files": len(manifests["PlatformConfig"]["files"]),
        "production_modified": False,
        "secrets_tested": False,
    }
    atomic_text(evidence / "result.json", json.dumps(result, indent=2, sort_keys=True) + "\n")
    atomic_text(evidence / "PASS", backup_id + "\n")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)

    backup_parser = sub.add_parser("backup")
    backup_parser.add_argument("--target-root", type=Path, required=True)
    backup_parser.add_argument("--tier", choices=("daily", "weekly", "manual"), default="manual")
    backup_parser.add_argument("--allow-local", action="store_true")

    verify_parser = sub.add_parser("verify")
    verify_parser.add_argument("manifest_dir", type=Path)

    restore_parser = sub.add_parser("restore-validate")
    restore_parser.add_argument("--ers", type=Path, required=True)
    restore_parser.add_argument("--hermes", type=Path, required=True)
    restore_parser.add_argument("--platform", type=Path, required=True)

    args = parser.parse_args()
    if args.command == "backup":
        result = create_backup(args.target_root, args.tier, args.allow_local)
    elif args.command == "verify":
        result = verify(args.manifest_dir)
    else:
        result = restore_validate(args.ers, args.hermes, args.platform)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
