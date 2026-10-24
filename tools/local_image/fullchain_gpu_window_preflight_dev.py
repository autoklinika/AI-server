#!/usr/bin/env python3
"""Read-only fail-closed staging integrity gate for future operator GPU window.

Does NOT grant RM resources, call Ollama inference, start/stop systemd,
modify files, contact Telegram or generate images.
"""
from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import sys

ROOT = Path(__file__).resolve().parents[2]
CHECK_SCRIPT = ROOT / "tools/local_image/prepare_comfy_fullchain_isolated_dev.py"
spec = importlib.util.spec_from_file_location("fullchain_snapshot_checks", CHECK_SCRIPT)
assert spec is not None and spec.loader is not None
snapshot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(snapshot)

STAGING = Path("/srv/ai-data/staging/comfy-fullchain-dev-20261024-guarded")
OLD_UNSAFE = Path("/srv/ai-data/staging/comfy-fullchain-dev-20261024")
MARKERS = (
    Path("/srv/ai-data/staging/comfy-ondemand-maintenance-dev-20261023/dev-residency.blocked"),
    Path("/srv/ai-data/staging/comfy-ondemand-faults-dev-20261024/dev-residency.blocked"),
    STAGING / "dev-residency.blocked",
)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _safe_regular_file(path: Path, owner: int) -> bool:
    try:
        s = path.lstat()
        return stat.S_ISREG(s.st_mode) and s.st_uid == owner and not path.is_symlink()
    except OSError:
        return False


def _safe_directory(path: Path, owner: int, *, strict: bool) -> bool:
    try:
        s = path.lstat()
        return (stat.S_ISDIR(s.st_mode) and s.st_uid == owner
                and not path.is_symlink()
                and (not strict or stat.S_IMODE(s.st_mode) == 0o700))
    except OSError:
        return False


def _snapshot_paths(repo_root: Path, staging: Path) -> list[str]:
    """All copied AI package files must byte-match the checked-out source."""
    problems: list[str] = []
    if not _safe_directory(staging / "src", os.getuid(), strict=True):
        problems.append("staging/src is not an owned private directory")
        return problems
    src_original = repo_root / "src/ai_bridge"
    src_staged = staging / "src/ai_bridge"
    if not src_original.is_dir() or not _safe_directory(src_staged, os.getuid(), strict=False):
        problems.append("staging/src/ai_bridge missing or unsafe")
        return problems
    def sources(tree: Path) -> dict[str, Path]:
        return {
            str(p.relative_to(tree)): p
            for p in tree.rglob("*")
            if p.is_file() and not p.name.endswith(".pyc")
            and "__pycache__" not in p.parts
        }
    expected = sources(src_original)
    found = sources(src_staged)
    if expected.keys() != found.keys():
        problems.append("staged package file list differs from DEV worktree")
    for name, original in expected.items():
        staged = found.get(name)
        if staged is None or not _safe_regular_file(staged, os.getuid()):
            problems.append("missing/untrusted staged package file: " + name)
            continue
        if name == "providers/media_admission.py":
            expected_text = snapshot.transform(
                "src/ai_bridge/providers/media_admission.py", original.read_text())
            actual = staged.read_text()
            if expected_text != actual:
                problems.append("DEV media-admission snapshot source drift")
        elif sha(original) != sha(staged):
            problems.append("DEV package snapshot source drift: " + name)
    return problems


def verify_snapshot(
    staging: Path = STAGING, repo_root: Path = ROOT, *, markers: tuple[Path, ...] = MARKERS,
) -> dict:
    problems: list[str] = []
    uid = os.getuid()
    if uid == 0:
        problems.append("read-only preflight must run as non-root")
    if staging != STAGING:
        problems.append("unapproved GPU staging root")
    if OLD_UNSAFE == staging:
        problems.append("obsolete DEV snapshot selected")
    if not _safe_directory(staging, uid, strict=True):
        problems.append("snapshot root not private directory owned by operator")
        return {"gate": "BLOCKED", "problems": problems}

    for dirname in ("tools", "src", "input", "output", "temp", "user",
                    "jobs", "hermes-inbound"):
        if not _safe_directory(staging / dirname, uid, strict=True):
            problems.append("invalid DEV directory: " + dirname)

    manifest_path = staging / "SOURCE_MANIFEST.json"
    if not _safe_regular_file(manifest_path, uid):
        problems.append("snapshot SHA256 manifest missing or unsafe")
    else:
        try:
            manifest = json.loads(manifest_path.read_text())
            if (manifest["kind"] != "DEV_ISOLATED_SOURCES_ONLY"
                    or manifest["gateway_port"] != 11656
                    or manifest["comfy_port"] != 11657
                    or Path(manifest["snapshot"]) != staging
                    or set(manifest["files"]) != set(snapshot.SOURCE_FILES)):
                raise ValueError("invalid manifest content")
            for relative in snapshot.SOURCE_FILES:
                original = repo_root / relative
                staged = staging / relative
                if (not _safe_regular_file(original, uid)
                        or not _safe_regular_file(staged, uid)):
                    problems.append("unexpected owner/file/symlink: " + relative)
                    continue
                entry = manifest["files"][relative]
                expected = snapshot.transform(relative, original.read_text())
                if entry["original_sha256"] != sha(original):
                    problems.append("original source SHA changed: " + relative)
                if (entry["snapshot_sha256"] != sha(staged)
                        or staged.read_text() != expected):
                    problems.append("snapshot/source mismatch: " + relative)
        except (ValueError, KeyError, TypeError, OSError, UnicodeDecodeError) as exc:
            problems.append("snapshot manifest invalid: " + type(exc).__name__)

    problems.extend(_snapshot_paths(repo_root, staging))

    for relative, symbol in (
        ("tools/local_image/hermes_foto_dispatch.py", "_send"),
        ("tools/hermes_resource_queue.py", "_notify"),
    ):
        target = staging / relative
        if not _safe_regular_file(target, uid):
            problems.append("cannot verify captured delivery: " + relative)
            continue
        try:
            tree = ast.parse(target.read_text())
            fn = next(x for x in tree.body if isinstance(x, ast.FunctionDef)
                      and x.name == symbol)
            code = ast.get_source_segment(target.read_text(), fn) or ""
            if ("DEV recipient refused" not in code
                    or "DEV_UNROUTABLE_NO_SEND" not in code
                    or "captured-" not in code
                    or "subprocess" in code or "hermes" in code):
                problems.append("live delivery was not conclusively disabled: " + symbol)
        except (OSError, ValueError, StopIteration, SyntaxError):
            problems.append("invalid captured delivery function: " + symbol)

    for rel in ("tools/local_image/generate_image.py",
                "tools/local_image/generate_image_edit.py"):
        executable = staging / rel
        if not _safe_regular_file(executable, uid) or not os.access(executable, os.X_OK):
            problems.append("DEV generator missing, unsafe or not executable: " + rel)
    active = [str(p) for p in markers if p.exists()]
    if active:
        problems.append("active DEV recovery marker already exists")

    return {
        "schema": 1,
        "kind": "FULLCHAIN_SNAPSHOT_READONLY_GATE",
        "gate": "PASS" if not problems else "BLOCKED",
        "problems": problems,
        "recovery_markers_present": active,
        "gateway_dev": "127.0.0.1:11656",
        "comfy_dev": "127.0.0.1:11657",
        "runtime": "NOT_STARTED",
        "gpu": "NOT_TOUCHED",
        "gpu_reuse_safe": "NOT_VERIFIED",
        "production_changed": False,
        "production_cutover": "NOT_AUTHORIZED",
    }


if __name__ == "__main__":
    if sys.argv[1:] != ["--check"]:
        print("Usage: fullchain_gpu_window_preflight_dev.py --check", file=sys.stderr)
        raise SystemExit(2)
    result = verify_snapshot()
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    raise SystemExit(0 if result["gate"] == "PASS" else 3)
