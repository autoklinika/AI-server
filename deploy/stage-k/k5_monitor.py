#!/usr/bin/env python3
"""Hourly Stage K backup health monitor with transition-only Telegram alerts."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

from common import atomic_text

TARGET_ROOT = Path("/mnt/AI_Platform")
STATUS_ROOT = Path("/srv/ai-data/platform/backup-status/stage-k")
MARKER = TARGET_ROOT / ".ai-platform-backup-target.json"
NOTIFIER_INSTALLED = Path.home() / "agent-control" / "stage-k" / "notify_telegram.py"
NOTIFIER_REPO = Path(__file__).resolve().parents[1] / "autopilot" / "notify_telegram.py"
MAX_BACKUP_AGE_HOURS = 36
MAX_WEEKLY_AGE_HOURS = 8 * 24
MIN_FREE_BYTES = 50 * 1024**3


def now() -> datetime:
    return datetime.now(timezone.utc)


def load_json(path: Path) -> dict[str, object] | None:
    try:
        value = json.loads(path.read_text())
        return value if isinstance(value, dict) else None
    except Exception:
        return None


def parsed_time(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def age_hours(value: object) -> float | None:
    stamp = parsed_time(value)
    if stamp is None:
        return None
    return (now() - stamp.astimezone(timezone.utc)).total_seconds() / 3600


def notify(event: str, message: str) -> None:
    notifier = NOTIFIER_INSTALLED if NOTIFIER_INSTALLED.is_file() else NOTIFIER_REPO
    if not notifier.is_file():
        return
    try:
        subprocess.run(
            [sys.executable, str(notifier), event, "K", message],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=20,
        )
    except Exception:
        # Notification delivery must never change backup/DR result semantics.
        return


def mount_state() -> tuple[bool, str]:
    result = subprocess.run(
        ["findmnt", "-T", str(TARGET_ROOT), "-n", "-o", "SOURCE,FSTYPE"],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    if result.returncode != 0:
        return False, "GlobalNAS mount unavailable"
    fields = result.stdout.split()
    if len(fields) != 2:
        return False, "GlobalNAS mount state invalid"
    source, fs_type = fields
    if source != "//globalnas.local/AI_Platform" or fs_type != "cifs":
        return False, "GlobalNAS mount source/type mismatch"
    return True, source
def check() -> dict[str, object]:
    STATUS_ROOT.mkdir(parents=True, exist_ok=True)
    issues: list[str] = []

    mounted, mount_detail = mount_state()
    if not mounted:
        issues.append(mount_detail)

    marker = load_json(MARKER) if mounted else None
    if marker is None:
        issues.append("Stage K NAS marker missing/invalid")
    elif (
        marker.get("purpose") != "ai-platform-stage-k"
        or marker.get("nas") != "GlobalNAS"
        or marker.get("share") != "AI_Platform"
    ):
        issues.append("Stage K NAS marker mismatch")

    daily = load_json(STATUS_ROOT / "daily.json")
    weekly = load_json(STATUS_ROOT / "weekly.json")
    pass_statuses = [
        item for item in (daily, weekly)
        if item and item.get("status") == "PASS"
    ]
    freshest_age: float | None = None
    if pass_statuses:
        ages = [
            age_hours(item.get("completed_at"))
            for item in pass_statuses
        ]
        ages = [value for value in ages if value is not None]
        if ages:
            freshest_age = min(ages)
    if freshest_age is None:
        issues.append("no successful automatic backup status")
    elif freshest_age > MAX_BACKUP_AGE_HOURS:
        issues.append(f"automatic backup stale: {freshest_age:.1f}h")

    weekly_age: float | None = None
    if not weekly or weekly.get("status") != "PASS":
        issues.append("weekly restore validation has no PASS")
    else:
        weekly_age = age_hours(weekly.get("completed_at"))
        if weekly_age is None:
            issues.append("weekly completion timestamp invalid")
        elif weekly_age > MAX_WEEKLY_AGE_HOURS:
            issues.append(f"weekly restore validation stale: {weekly_age:.1f}h")

    free_bytes: int | None = None
    if mounted:
        try:
            free_bytes = shutil.disk_usage(TARGET_ROOT).free
            if free_bytes < MIN_FREE_BYTES:
                issues.append("GlobalNAS free space below 50 GiB")
        except OSError:
            issues.append("GlobalNAS free space check failed")

    status = {
        "status": "PASS" if not issues else "FAIL",
        "checked_at": now().isoformat(),
        "issues": issues,
        "mount": mount_detail,
        "freshest_backup_age_hours": (
            round(freshest_age, 3) if freshest_age is not None else None
        ),
        "weekly_age_hours": (
            round(weekly_age, 3) if weekly_age is not None else None
        ),
        "nas_free_bytes": free_bytes,
        "secrets_recovery_key_decision": "DEFERRED_NON_BLOCKING",
    }
    atomic_text(
        STATUS_ROOT / "monitor.json",
        json.dumps(status, indent=2, sort_keys=True) + "\n",
        mode=0o600,
    )
    state_path = STATUS_ROOT / "monitor-alert-state.json"
    previous = load_json(state_path) or {}
    digest = hashlib.sha256(
        "\n".join(sorted(issues)).encode()
    ).hexdigest() if issues else ""

    if issues and previous.get("issue_digest") != digest:
        notify(
            "BLOCKED",
            "Backup/DR monitor wykrył problem: " + "; ".join(issues[:3]),
        )
    elif not issues and previous.get("issue_digest"):
        notify("COMPLETE", "Backup/DR monitor wrócił do stanu PASS.")

    atomic_text(
        state_path,
        json.dumps(
            {
                "issue_digest": digest,
                "updated_at": now().isoformat(),
                "status": status["status"],
            },
            indent=2,
            sort_keys=True,
        ) + "\n",
        mode=0o600,
    )
    return status


def main() -> None:
    print(json.dumps(check(), sort_keys=True))


if __name__ == "__main__":
    main()
