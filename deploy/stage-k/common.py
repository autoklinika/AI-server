#!/usr/bin/env python3
"""Shared fail-closed primitives for Stage K backup and recovery."""
from __future__ import annotations

import hashlib
import importlib.util
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
STAGE_J_DATA = ROOT / "deploy/stage-j/data_prepare.py"
ACTIVE_LINK = Path("/opt/ai-platform/current")
OBJECT_ROOT = Path("/srv/ai-data/knowledge/canonical/objects")
DEFAULT_BACKUP_ROOT = Path("/srv/ai-data/backups/stage-k")


class StageKError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise StageKError(message)


def run(args: list[str], *, env: dict[str, str] | None = None,
        timeout: int = 60, cwd: Path | None = None) -> str:
    result = subprocess.run(
        [str(item) for item in args],
        check=False, capture_output=True, text=True,
        env=env, timeout=timeout, cwd=str(cwd) if cwd else None,
    )
    if result.returncode != 0:
        raise StageKError(
            f"command failed rc={result.returncode}: {Path(str(args[0])).name}"
        )
    return result.stdout


def stage_j_data_helper():
    spec = importlib.util.spec_from_file_location("stage_j_data_prepare", STAGE_J_DATA)
    require(spec is not None and spec.loader is not None, "Stage J helper unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def production_postgres_env() -> dict[str, str]:
    helper = stage_j_data_helper()
    return helper.postgres_env(helper.active_database_url())


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_text(path: Path, text: str, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".tmp-{os.getpid()}")
    tmp.write_text(text)
    os.chmod(tmp, mode)
    os.replace(tmp, path)


def active_release() -> Path:
    release = ACTIVE_LINK.resolve(strict=True)
    require(release.is_dir(), "active release is not a directory")
    return release


def machine_identity_hash() -> str:
    value = Path("/etc/machine-id").read_text().strip()
    require(bool(value), "machine-id unavailable")
    return hashlib.sha256(value.encode()).hexdigest()


def git_head(repo: Path = ROOT) -> str:
    value = run(["git", "-C", str(repo), "rev-parse", "HEAD"]).strip()
    require(len(value) == 40, "invalid git HEAD")
    return value
