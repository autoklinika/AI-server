#!/usr/bin/env python3
"""Stage K scheduled backup/restore orchestration."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

from common import atomic_text, git_head, require

ROOT = Path(__file__).resolve().parents[2]
STAGE_K = Path(__file__).resolve().parent
TARGET_ROOT = Path("/mnt/AI_Platform")
STATUS_ROOT = Path("/srv/ai-data/platform/backup-status/stage-k")
LOCK_PATH = Path("/srv/ai-data/platform/backup-status/stage-k/run.lock")
NOTIFIER_INSTALLED = Path.home() / "agent-control" / "stage-k" / "notify_telegram.py"
NOTIFIER_REPO = ROOT / "deploy" / "autopilot" / "notify_telegram.py"


class CommandError(RuntimeError):
    def __init__(self, label: str, returncode: int):
        super().__init__(f"{label} failed rc={returncode}")
        self.label = label
        self.returncode = returncode


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_last_json(text: str, label: str) -> dict[str, object]:
    for raw in reversed(text.splitlines()):
        line = raw.strip()
        if not line:
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    raise RuntimeError(f"{label} produced no JSON result")


def run_json(label: str, args: list[str], timeout: int) -> dict[str, object]:
    result = subprocess.run(
        args,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=ROOT,
        env=os.environ.copy(),
    )
    if result.returncode != 0:
        raise CommandError(label, result.returncode)
    value = parse_last_json(result.stdout, label)
    require(value.get("status") == "PASS", f"{label} did not return PASS")
    return value
def notify(event: str, message: str) -> None:
    notifier = NOTIFIER_INSTALLED if NOTIFIER_INSTALLED.is_file() else NOTIFIER_REPO
    if not notifier.is_file():
        return
    subprocess.run(
        [str(notifier), event, "K", message],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=20,
    )


def write_status(tier: str, payload: dict[str, object]) -> None:
    STATUS_ROOT.mkdir(parents=True, exist_ok=True)
    atomic_text(
        STATUS_ROOT / f"{tier}.json",
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        mode=0o600,
    )


def latest_id(path: str) -> str:
    return Path(path).name


def run(tier: str) -> dict[str, object]:
    require(tier in {"daily", "weekly"}, "invalid K5 tier")
    STATUS_ROOT.mkdir(parents=True, exist_ok=True)
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    started_at = now_iso()
    phase = "preflight"

    with LOCK_PATH.open("a+") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("another Stage K backup run is active") from exc

        write_status(tier, {
            "status": "RUNNING",
            "tier": tier,
            "started_at": started_at,
            "phase": phase,
            "stage_k_code_git_sha": git_head(),
            "secrets_automation": "DEFERRED",
        })

        try:
            phase = "knowledge_backup"
            k2 = run_json(
                phase,
                [sys.executable, str(STAGE_K / "backup.py"),
                 "--target-root", str(TARGET_ROOT), "--tier", tier],
                timeout=3600,
            )

            phase = "domain_backup"
            k3 = run_json(
                phase,
                [sys.executable, str(STAGE_K / "k3_domains.py"), "backup",
                 "--target-root", str(TARGET_ROOT), "--tier", tier],
                timeout=3600,
            )
            phase = "verify_knowledge"
            knowledge_verify = run_json(
                phase,
                [sys.executable, str(STAGE_K / "verify_backup.py"),
                 str(k2["knowledge_set"])],
                timeout=900,
            )
            phase = "verify_wvc"
            wvc_verify = run_json(
                phase,
                [sys.executable, str(STAGE_K / "verify_backup.py"),
                 str(k2["wvc_set"])],
                timeout=900,
            )

            domain_verify: dict[str, object] = {}
            for name, key in (
                ("ers", "ers_manifest"),
                ("hermes", "hermes_manifest"),
                ("platform", "platform_manifest"),
            ):
                phase = f"verify_{name}"
                domain_verify[name] = run_json(
                    phase,
                    [sys.executable, str(STAGE_K / "k3_domains.py"),
                     "verify", str(k3[key])],
                    timeout=900,
                )

            restore: dict[str, object] = {}
            if tier == "weekly":
                phase = "restore_knowledge"
                restore["knowledge"] = run_json(
                    phase,
                    [sys.executable, str(STAGE_K / "restore_validate.py"),
                     str(k2["knowledge_set"])],
                    timeout=7200,
                )
                phase = "restore_domains"
                restore["domains"] = run_json(
                    phase,
                    [sys.executable, str(STAGE_K / "k3_domains.py"),
                     "restore-validate",
                     "--ers", str(k3["ers_manifest"]),
                     "--hermes", str(k3["hermes_manifest"]),
                     "--platform", str(k3["platform_manifest"])],
                    timeout=1800,
                )

            phase = "retention"
            keep = 30 if tier == "daily" else 12
            retention = run_json(
                phase,
                [sys.executable, str(STAGE_K / "k5_retention.py"),
                 "--target-root", str(TARGET_ROOT),
                 "--tier", tier, "--keep", str(keep),
                 "--restore-evidence-keep", "12"],
                timeout=1800,
            )
            usage = shutil.disk_usage(TARGET_ROOT)
            result = {
                "status": "PASS",
                "tier": tier,
                "started_at": started_at,
                "completed_at": now_iso(),
                "duration_seconds": round(time.monotonic() - started, 3),
                "stage_k_code_git_sha": git_head(),
                "knowledge_backup_id": latest_id(str(k2["knowledge_set"])),
                "domain_backup_id": str(k3["backup_id"]),
                "knowledge_verify": knowledge_verify,
                "wvc_verify": wvc_verify,
                "domain_verify": domain_verify,
                "restore_validation": restore,
                "retention": retention,
                "nas_free_bytes": usage.free,
                "secrets_automation": "DEFERRED",
                "manual_sets_touched": False,
            }
            write_status(tier, result)
            if tier == "weekly":
                notify(
                    "COMPLETE",
                    "Weekly backup + pełny restore validation zakończone PASS.",
                )
            return result
        except Exception as exc:
            failure = {
                "status": "FAIL",
                "tier": tier,
                "started_at": started_at,
                "failed_at": now_iso(),
                "duration_seconds": round(time.monotonic() - started, 3),
                "phase": phase,
                "error_type": type(exc).__name__,
                "error": str(exc),
                "stage_k_code_git_sha": git_head(),
                "secrets_automation": "DEFERRED",
            }
            write_status(tier, failure)
            notify("BLOCKED", f"Automatyczny backup {tier} FAIL w fazie {phase}.")
            raise


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("tier", choices=("daily", "weekly"))
    args = parser.parse_args()
    print(json.dumps(run(args.tier), sort_keys=True))


if __name__ == "__main__":
    main()
