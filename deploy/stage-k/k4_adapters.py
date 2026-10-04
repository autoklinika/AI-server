#!/usr/bin/env python3
"""Stage K backup/verify/restore validation for active production LoRA adapters."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import stat
import tarfile
import time

from backup import verify_target
from common import atomic_text, file_sha256, git_head, machine_identity_hash, require

SOURCE_ROOT = Path("/srv/ai-data/training/p5/adapters")
RUNTIME_ROOT = Path("/srv/ai-data/training/p5/runtime-adapters")
EVIDENCE_ROOT = Path("/srv/ai-data/backups/stage-k/adapter-restore-validation")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def source_identity() -> dict[str, object]:
    return {
        "hostname": socket.gethostname(),
        "machine_id_sha256": machine_identity_hash(),
        "stage_k_code_git_sha": git_head(),
    }


def ensure_below(path: Path, root: Path, label: str) -> Path:
    resolved = path.resolve(strict=True)
    base = root.resolve(strict=True)
    require(resolved != base and base in resolved.parents, f"{label} escapes expected root")
    return resolved


def active_adapter_names() -> list[str]:
    """Runtime current.gguf is the production/deployed marker.

    A runtime marker without a matching source current alias is a hard failure:
    such an adapter could run but could not be reproducibly recovered.
    """
    require(SOURCE_ROOT.is_dir(), f"adapter source root missing: {SOURCE_ROOT}")
    require(RUNTIME_ROOT.is_dir(), f"adapter runtime root missing: {RUNTIME_ROOT}")
    names: list[str] = []
    for runtime_dir in sorted(RUNTIME_ROOT.iterdir()):
        if not runtime_dir.is_dir():
            continue
        runtime_alias = runtime_dir / "current.gguf"
        if not runtime_alias.exists() and not runtime_alias.is_symlink():
            continue
        require(runtime_alias.is_symlink(), f"runtime current.gguf must be symlink: {runtime_alias}")
        source_alias = SOURCE_ROOT / runtime_dir.name / "current"
        require(source_alias.is_symlink(), f"deployed adapter missing source current alias: {runtime_dir.name}")
        names.append(runtime_dir.name)
    require(bool(names), "no active production adapters selected for backup")
    return names


def create_tar(archive: Path, base: Path, files: list[Path], prefix: str) -> None:
    require(bool(files), f"no files selected for {prefix}")
    archive.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive, "w:gz", compresslevel=6) as tf:
        for source in files:
            require(source.is_file() and not source.is_symlink(), f"invalid snapshot file: {source}")
            rel = source.relative_to(base).as_posix()
            tf.add(source, arcname=f"{prefix}/{rel}", recursive=False)


def manifest_from_tar(archive: Path, prefix: str) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    with tarfile.open(archive, "r:gz") as tf:
        for member in sorted(tf.getmembers(), key=lambda item: item.name):
            require(member.isfile(), f"unexpected non-file tar member: {member.name}")
            expected = prefix.rstrip("/") + "/"
            require(member.name.startswith(expected), f"tar prefix mismatch: {member.name}")
            rel = member.name[len(expected):]
            require(rel and not rel.startswith("/") and ".." not in Path(rel).parts,
                    f"unsafe tar member: {member.name}")
            stream = tf.extractfile(member)
            require(stream is not None, f"cannot read tar member: {member.name}")
            digest = hashlib.sha256()
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
            rows.append({
                "path": rel,
                "bytes": int(member.size),
                "sha256": digest.hexdigest(),
                "mode": oct(stat.S_IMODE(member.mode)),
            })
    return rows


def direct_manifest_adapter_hashes(source_files: list[Path]) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for path in source_files:
        if path.suffix.lower() != ".json" or "manifest" not in path.name.lower():
            continue
        try:
            data = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        value = data.get("adapter_sha256") if isinstance(data, dict) else None
        if isinstance(value, str) and len(value) == 64:
            hashes[path.name] = value.lower()
    return hashes


def collect_adapter(name: str, staging: Path, root: Path) -> dict[str, object]:
    require(name and "/" not in name and name not in {".", ".."}, "unsafe adapter name")
    source_dir = SOURCE_ROOT / name
    runtime_dir = RUNTIME_ROOT / name
    source_alias = source_dir / "current"
    runtime_alias = runtime_dir / "current.gguf"

    require(source_alias.is_symlink(), f"source current alias missing: {name}")
    require(runtime_alias.is_symlink(), f"runtime current.gguf alias missing: {name}")
    source_real = ensure_below(source_alias, source_dir, f"{name} source current")
    runtime_real = ensure_below(runtime_alias, runtime_dir, f"{name} runtime current.gguf")
    require(source_real.is_dir(), f"source current target is not directory: {name}")
    require(runtime_real.is_file(), f"runtime current target is not file: {name}")

    weights = source_real / "adapter_model.safetensors"
    config = source_real / "adapter_config.json"
    require(weights.is_file(), f"adapter weights missing: {name}")
    require(config.is_file(), f"adapter config missing: {name}")
    source_sha = file_sha256(weights)

    source_files = sorted(
        item for item in source_real.iterdir()
        if item.is_file() and not item.is_symlink()
    )
    require(weights in source_files and config in source_files,
            f"mandatory source files not selected: {name}")

    declared_hashes = direct_manifest_adapter_hashes(source_files)
    for manifest_name, declared in declared_hashes.items():
        require(declared == source_sha,
                f"{name} source hash mismatch in {manifest_name}")

    runtime_metadata = sorted(
        item for item in runtime_dir.iterdir()
        if item.is_file() and not item.is_symlink() and item.suffix.lower() != ".gguf"
    )

    adapter_stage = staging / name
    adapter_stage.mkdir(parents=True, exist_ok=False)
    source_archive = adapter_stage / "source.tar.gz"
    create_tar(source_archive, source_real, source_files, "source")
    source_rows = manifest_from_tar(source_archive, "source")

    runtime_copy = adapter_stage / "runtime.gguf"
    shutil.copy2(runtime_real, runtime_copy)
    runtime_sha = file_sha256(runtime_real)
    require(file_sha256(runtime_copy) == runtime_sha, f"runtime copy hash mismatch: {name}")
    require(runtime_copy.stat().st_size == runtime_real.stat().st_size,
            f"runtime copy size mismatch: {name}")

    metadata_archive: Path | None = None
    metadata_rows: list[dict[str, object]] = []
    if runtime_metadata:
        metadata_archive = adapter_stage / "runtime-metadata.tar.gz"
        create_tar(metadata_archive, runtime_dir, runtime_metadata, "runtime-metadata")
        metadata_rows = manifest_from_tar(metadata_archive, "runtime-metadata")

    return {
        "name": name,
        "adapter_kind": "standalone_lora_not_merged",
        "source_current_alias": str(source_alias),
        "source_selected": str(source_real),
        "source_adapter_sha256": source_sha,
        "source_adapter_config_sha256": file_sha256(config),
        "source_declared_hashes": declared_hashes,
        "source_archive": {
            "path": None,
            "bytes": source_archive.stat().st_size,
            "sha256": file_sha256(source_archive),
            "files": source_rows,
        },
        "runtime_current_alias": str(runtime_alias),
        "runtime_selected": str(runtime_real),
        "runtime_gguf": {
            "path": None,
            "bytes": runtime_copy.stat().st_size,
            "sha256": runtime_sha,
        },
        "runtime_metadata_archive": (
            {
                "path": None,
                "bytes": metadata_archive.stat().st_size,
                "sha256": file_sha256(metadata_archive),
                "files": metadata_rows,
            } if metadata_archive is not None else None
        ),
    }


def write_manifest_set(directory: Path, manifest: dict[str, object]) -> None:
    directory.mkdir(parents=True, exist_ok=False)
    path = directory / "manifest.json"
    atomic_text(path, json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    atomic_text(directory / "manifest.sha256", file_sha256(path) + "  manifest.json\n")
    atomic_text(directory / "COMPLETE", str(manifest["backup_id"]) + "\n")


def create_backup(target_root: Path, tier: str, allow_local: bool) -> dict[str, object]:
    root = target_root.resolve()
    require(root.name == "AI_Platform", "target root must be AI_Platform")
    target = verify_target(root, allow_local)
    require(tier in {"daily", "weekly", "manual"}, "invalid adapter backup tier")

    names = active_adapter_names()
    backup_id = utc_now().strftime("%Y%m%dT%H%M%SZ")
    started = utc_now()
    staging = root / ".incomplete" / f"adapters-{backup_id}.{os.getpid()}"
    snapshot_stage = staging / "snapshot"
    snapshot_stage.mkdir(parents=True, mode=0o700)

    rows = [collect_adapter(name, snapshot_stage, root) for name in names]
    snapshot = root / "Adapters" / "snapshots" / tier / backup_id
    snapshot.parent.mkdir(parents=True, exist_ok=True)
    require(not snapshot.exists(), f"adapter snapshot already exists: {snapshot}")
    os.replace(snapshot_stage, snapshot)

    for row in rows:
        name = str(row["name"])
        base = snapshot / name
        row["source_archive"]["path"] = (base / "source.tar.gz").relative_to(root).as_posix()
        row["runtime_gguf"]["path"] = (base / "runtime.gguf").relative_to(root).as_posix()
        metadata = row.get("runtime_metadata_archive")
        if isinstance(metadata, dict):
            metadata["path"] = (base / "runtime-metadata.tar.gz").relative_to(root).as_posix()

    manifest = {
        "manifest_schema_version": 1,
        "status": "COMPLETE",
        "domain": "Adapters",
        "backup_id": backup_id,
        "tier": tier,
        "created_at": started.isoformat(),
        "completed_at": utc_now().isoformat(),
        "target": target,
        "source": source_identity(),
        "selection_policy": "runtime current.gguf symlink + matching source current symlink",
        "checkpoint_directories_included": False,
        "secrets_included": False,
        "adapters": rows,
    }
    manifest_dir = root / "Adapters" / "manifests" / tier / backup_id
    write_manifest_set(manifest_dir, manifest)

    try:
        staging.rmdir()
        staging.parent.rmdir()
    except OSError:
        pass

    return {
        "status": "PASS",
        "backup_id": backup_id,
        "adapter_manifest": str(manifest_dir),
        "adapter_count": len(rows),
        "adapters": names,
    }


def platform_root(path: Path) -> Path:
    resolved = path.resolve()
    for candidate in (resolved, *resolved.parents):
        if candidate.name == "AI_Platform":
            return candidate
    raise RuntimeError("adapter manifest is not below AI_Platform")


def resolve_ref(manifest_dir: Path, relative: str) -> Path:
    root = platform_root(manifest_dir)
    path = (root / relative).resolve()
    require(path == root or root in path.parents, "adapter manifest reference escapes AI_Platform")
    return path


def load_verified_manifest(manifest_dir: Path) -> dict[str, object]:
    manifest_dir = manifest_dir.resolve()
    manifest_path = manifest_dir / "manifest.json"
    checksum = manifest_dir / "manifest.sha256"
    complete = manifest_dir / "COMPLETE"
    require(manifest_path.is_file(), "adapter manifest.json missing")
    require(checksum.is_file(), "adapter manifest.sha256 missing")
    require(complete.is_file(), "adapter COMPLETE missing")
    require(file_sha256(manifest_path) == checksum.read_text().split()[0],
            "adapter manifest checksum mismatch")
    manifest = json.loads(manifest_path.read_text())
    require(manifest.get("status") == "COMPLETE", "adapter manifest status invalid")
    require(manifest.get("domain") == "Adapters", "adapter manifest domain invalid")
    require(complete.read_text().strip() == manifest.get("backup_id"),
            "adapter COMPLETE mismatch")
    require(manifest.get("checkpoint_directories_included") is False,
            "checkpoint backup policy mismatch")
    require(manifest.get("secrets_included") is False,
            "adapter backup unexpectedly includes secrets")

    adapters = manifest.get("adapters")
    require(isinstance(adapters, list) and bool(adapters), "adapter manifest has no adapters")
    seen: set[str] = set()
    for row in adapters:
        require(isinstance(row, dict), "invalid adapter manifest row")
        name = str(row.get("name", ""))
        require(name and name not in seen, f"duplicate/invalid adapter row: {name}")
        seen.add(name)

        source = row["source_archive"]
        source_archive = resolve_ref(manifest_dir, source["path"])
        require(source_archive.is_file(), f"source archive missing: {name}")
        require(source_archive.stat().st_size == int(source["bytes"]),
                f"source archive size mismatch: {name}")
        require(file_sha256(source_archive) == source["sha256"],
                f"source archive checksum mismatch: {name}")
        source_rows = manifest_from_tar(source_archive, "source")
        require(source_rows == source["files"], f"source archive file manifest mismatch: {name}")
        weights = [item for item in source_rows if item["path"] == "adapter_model.safetensors"]
        require(len(weights) == 1, f"adapter weights missing from backup: {name}")
        require(weights[0]["sha256"] == row["source_adapter_sha256"],
                f"adapter source SHA mismatch inside backup: {name}")

        runtime = row["runtime_gguf"]
        runtime_file = resolve_ref(manifest_dir, runtime["path"])
        require(runtime_file.is_file(), f"runtime GGUF missing: {name}")
        require(runtime_file.stat().st_size == int(runtime["bytes"]),
                f"runtime GGUF size mismatch: {name}")
        require(file_sha256(runtime_file) == runtime["sha256"],
                f"runtime GGUF checksum mismatch: {name}")

        metadata = row.get("runtime_metadata_archive")
        if isinstance(metadata, dict):
            archive = resolve_ref(manifest_dir, metadata["path"])
            require(archive.is_file(), f"runtime metadata archive missing: {name}")
            require(archive.stat().st_size == int(metadata["bytes"]),
                    f"runtime metadata size mismatch: {name}")
            require(file_sha256(archive) == metadata["sha256"],
                    f"runtime metadata checksum mismatch: {name}")
            require(manifest_from_tar(archive, "runtime-metadata") == metadata["files"],
                    f"runtime metadata file manifest mismatch: {name}")
    return manifest


def verify(manifest_dir: Path) -> dict[str, object]:
    manifest = load_verified_manifest(manifest_dir)
    adapters = manifest["adapters"]
    return {
        "status": "PASS",
        "domain": "Adapters",
        "backup_id": manifest["backup_id"],
        "adapter_count": len(adapters),
        "adapters": [row["name"] for row in adapters],
        "source_bytes": sum(int(row["source_archive"]["bytes"]) for row in adapters),
        "runtime_bytes": sum(int(row["runtime_gguf"]["bytes"]) for row in adapters),
    }


def safe_extract(archive: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive, "r:gz") as tf:
        members = tf.getmembers()
        for member in members:
            require(member.isfile(), f"unsafe adapter tar member type: {member.name}")
            rel = Path(member.name)
            require(not rel.is_absolute() and ".." not in rel.parts,
                    f"unsafe adapter tar member path: {member.name}")
        tf.extractall(destination, members=members, filter="data")


def validate_files(base: Path, prefix: str, rows: list[dict[str, object]]) -> None:
    for row in rows:
        path = base / prefix / str(row["path"])
        require(path.is_file(), f"restored adapter file missing: {row['path']}")
        require(path.stat().st_size == int(row["bytes"]),
                f"restored adapter file size mismatch: {row['path']}")
        require(file_sha256(path) == row["sha256"],
                f"restored adapter file hash mismatch: {row['path']}")


def restore_validate(manifest_dir: Path) -> dict[str, object]:
    manifest = load_verified_manifest(manifest_dir)
    backup_id = str(manifest["backup_id"])
    stamp = utc_now().strftime("%Y%m%dT%H%M%SZ")
    evidence = EVIDENCE_ROOT / f"{backup_id}-{stamp}-{os.getpid()}"
    evidence.mkdir(parents=True, mode=0o700)
    started = time.monotonic()

    restored: list[str] = []
    for row in manifest["adapters"]:
        name = str(row["name"])
        target = evidence / name
        source = row["source_archive"]
        source_archive = resolve_ref(manifest_dir, source["path"])
        safe_extract(source_archive, target)
        validate_files(target, "source", source["files"])

        runtime = row["runtime_gguf"]
        runtime_source = resolve_ref(manifest_dir, runtime["path"])
        runtime_target = target / "runtime.gguf"
        shutil.copy2(runtime_source, runtime_target)
        require(file_sha256(runtime_target) == runtime["sha256"],
                f"restored runtime GGUF hash mismatch: {name}")

        metadata = row.get("runtime_metadata_archive")
        if isinstance(metadata, dict):
            archive = resolve_ref(manifest_dir, metadata["path"])
            safe_extract(archive, target)
            validate_files(target, "runtime-metadata", metadata["files"])
        restored.append(name)

    result = {
        "status": "PASS",
        "backup_id": backup_id,
        "duration_seconds": round(time.monotonic() - started, 3),
        "evidence_dir": str(evidence),
        "adapter_count": len(restored),
        "adapters": restored,
        "production_modified": False,
    }
    atomic_text(evidence / "result.json", json.dumps(result, indent=2, sort_keys=True) + "\n")
    atomic_text(evidence / "source-backup.txt", str(manifest_dir.resolve()) + "\n")
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
    restore_parser.add_argument("manifest_dir", type=Path)

    args = parser.parse_args()
    if args.command == "backup":
        result = create_backup(args.target_root, args.tier, args.allow_local)
    elif args.command == "verify":
        result = verify(args.manifest_dir)
    else:
        result = restore_validate(args.manifest_dir)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
