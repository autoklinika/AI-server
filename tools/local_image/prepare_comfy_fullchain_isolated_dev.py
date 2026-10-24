#!/usr/bin/env python3
"""Create a DEV-only snapshot for future supervised full-chain acceptance.

No network calls, model execution, systemd changes, or Telegram delivery.
Never modifies originals or reuses the production HTTP ports.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import pwd
import shutil
import sys

REPO = Path(__file__).resolve().parents[2]
STAGING = Path("/srv/ai-data/staging")
TARGET = STAGING / "comfy-fullchain-dev-20261024-captured"
SOURCE_FILES = (
    "tools/local_image/hermes_foto_dispatch_global.py",
    "tools/local_image/hermes_foto_dispatch.py",
    "tools/local_image/hermes_foto_prompt_compiler.py",
    "tools/hermes_resource_queue.py",
    "tools/local_image/generate_image.py",
    "tools/local_image/generate_image_edit.py",
    "src/ai_bridge/providers/media_admission.py",
)
PORT_GATEWAY_FILES = (
    "tools/local_image/hermes_foto_prompt_compiler.py",
    "tools/hermes_resource_queue.py",
    "src/ai_bridge/providers/media_admission.py",
)
GENERATORS = ("tools/local_image/generate_image.py",
              "tools/local_image/generate_image_edit.py")


def patch_one(text: str, old: str, new: str, expected: int = 1) -> str:
    if text.count(old) != expected:
        raise RuntimeError(f"snapshot source unexpectedly changed: {old[:70]}")
    return text.replace(old, new)


def replace_function(source: str, beginning: str, following: str, stub: str) -> str:
    if source.count(beginning) != 1 or source.count(following) != 1:
        raise RuntimeError("DEV delivery capture source drift")
    left = source.index(beginning)
    right = source.index(following, left + len(beginning))
    return source[:left] + stub + source[right:]


def transform(rel: str, source: str) -> str:
    # A copied worker must be incapable of sending notifications to real chats.
    # Only the fixed non-routable DEV target can write to a local capture file.
    if rel == "tools/local_image/hermes_foto_dispatch.py":
        source = replace_function(
            source, "def _send(target:", "\n\ndef worker(",
            'def _send(target: str, message: str, *, timeout: int = 120) -> None:\n'
            '    if target != "telegram:DEV_UNROUTABLE_NO_SEND":\n'
            '        raise FotoDispatchError("DEV recipient refused")\n'
            f'    with open("{TARGET}/captured-deliveries.jsonl", "a", encoding="utf-8") as capture:\n'
            '        capture.write(json.dumps({"target": "DEV_CAPTURE_ONLY", "message": message}, ensure_ascii=False) + "\\n")\n',
        )
    if rel == "tools/hermes_resource_queue.py":
        source = replace_function(
            source, "def _notify(target:", "\n\ndef _notify_best_effort(",
            'def _notify(target: str | None, message: str | None) -> None:\n'
            '    if not message or target is None:\n'
            '        return\n'
            '    if target != "telegram:DEV_UNROUTABLE_NO_SEND":\n'
            '        raise ResourceQueueError("DEV recipient refused")\n'
            f'    with open("{TARGET}/captured-queue.jsonl", "a", encoding="utf-8") as capture:\n'
            '        capture.write(json.dumps({"target": "DEV_CAPTURE_ONLY", "message": message}, ensure_ascii=False) + "\\n")\n',
        )
    if rel in PORT_GATEWAY_FILES:
        if "11435" not in source:
            raise RuntimeError("expected production gateway reference absent")
        source = source.replace("11435", "11656")
        if "11435" in source:
            raise RuntimeError("production gateway reference remained")
    if rel in GENERATORS:
        source = patch_one(source,
            'COMFY = "http://127.0.0.1:8188"',
            'COMFY = "http://127.0.0.1:11657"')
        source = patch_one(source,
            'OUTPUT = Path("/srv/ai-data/comfyui-output")',
            f'OUTPUT = Path("{TARGET}/output")')
    if rel == "tools/local_image/generate_image.py":
        source = patch_one(source, 'default=1024)', 'default=256)', expected=2)
        source = patch_one(source,
            'lock_path = "/tmp/generate-image.lock"',
            f'lock_path = "{TARGET}/generate-image.lock"')
    if rel == "tools/local_image/generate_image_edit.py":
        source = patch_one(source,
            'COMFY_INPUT = Path("/opt/comfyui/data/input")',
            f'COMFY_INPUT = Path("{TARGET}/input")')
    if rel in PORT_GATEWAY_FILES + GENERATORS:
        for unsafe in ("127.0.0.1:11435", "127.0.0.1:8188"):
            if unsafe in source:
                raise RuntimeError(f"production endpoint remained: {rel}")
    return source


def sha(text: bytes) -> str:
    return hashlib.sha256(text).hexdigest()


def verify_source() -> dict:
    if os.getuid() != pwd.getpwnam("harrypotter").pw_uid:
        raise RuntimeError("snapshot must be prepared by service user harrypotter")
    if TARGET.is_symlink() or TARGET.exists():
        raise RuntimeError("snapshot already exists: do not overwrite an earlier run")
    if not STAGING.is_dir() or STAGING.is_symlink():
        raise RuntimeError("staging root invalid")
    report = {"schema": 1, "kind": "DEV_ISOLATED_SOURCES_ONLY",
              "gateway_port": 11656, "comfy_port": 11657,
              "production_modified": False, "gpu_executed": False,
              "telegram_sent": False, "snapshot": str(TARGET), "files": {}}
    for rel in SOURCE_FILES:
        path = REPO / rel
        if not path.is_file() or path.is_symlink():
            raise RuntimeError(f"untrusted source file: {rel}")
        original = path.read_bytes()
        updated = transform(rel, original.decode("utf-8")).encode("utf-8")
        report["files"][rel] = {
            "original_sha256": sha(original), "snapshot_sha256": sha(updated),
            "changed": original != updated,
        }
    return report


def prepare() -> dict:
    report = verify_source()
    TARGET.mkdir(mode=0o700, parents=False, exist_ok=False)
    os.chmod(TARGET, 0o700)
    for dirname in ("output", "input", "temp", "user", "tools", "src"):
        d = TARGET / dirname
        d.mkdir(mode=0o700)
        os.chmod(d, 0o700)
    # Include only source code; never copy production configs, model files or credentials.
    shutil.copytree(REPO / "src/ai_bridge", TARGET / "src/ai_bridge",
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    for rel in SOURCE_FILES:
        original = (REPO / rel).read_text(encoding="utf-8")
        updated = transform(rel, original)
        path = TARGET / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(updated, encoding="utf-8")
        os.chmod(path, 0o700 if rel in GENERATORS else 0o600)
        if sha(path.read_bytes()) != report["files"][rel]["snapshot_sha256"]:
            raise RuntimeError(f"snapshot hash mismatch: {rel}")
    manifest = TARGET / "SOURCE_MANIFEST.json"
    manifest.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    os.chmod(manifest, 0o600)
    return report


def main() -> int:
    if sys.argv[1:] not in (["--check"], ["--prepare"]):
        print("Usage: python prepare_comfy_fullchain_isolated_dev.py --check|--prepare",
              file=sys.stderr)
        return 2
    try:
        if sys.argv[1] == "--prepare":
            report = prepare()
            outcome = "DEV_SNAPSHOT_PREPARED_NO_EXECUTION"
        else:
            report = verify_source()
            outcome = "DEV_SNAPSHOT_SOURCE_STATIC_PASS"
    except (OSError, RuntimeError, UnicodeDecodeError) as exc:
        print(f"DEV_SNAPSHOT_BLOCKED: {exc}", file=sys.stderr)
        return 3
    print(outcome)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
