"""Read-only operator snapshot for AI Control Center.

This module intentionally publishes a small, explicit allowlist. It never returns
raw backup manifests, secret material, arbitrary filesystem paths or commands.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Iterable


_CURRENT_RELEASE = Path("/opt/ai-platform/current")
_BACKUP_STATUS = Path("/srv/ai-data/platform/backup-status/stage-k")
_MAX_STATUS_BYTES = 1_048_576


def _read_json(path: Path) -> dict:
    try:
        if not path.is_file() or path.stat().st_size > _MAX_STATUS_BYTES:
            return {}
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def _release(root: Path) -> dict:
    allowed = {
        "release_id", "stage", "source_git_sha", "migration_version",
        "platform_api_contract_version", "observability_contract_version",
        "knowledge_service_contract_version", "ers_domain_contract_version",
        "crt_domain_contract_version", "control_center_contract_version",
    }
    try:
        values = {}
        for line in (root / "RELEASE").read_text(encoding="utf-8").splitlines():
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            if key in allowed:
                values[key] = value
        return {"status": "ready", **values} if values.get("release_id") else {"status": "unavailable"}
    except OSError:
        return {"status": "unavailable"}


def _disk(identifier: str, label: str, path: Path) -> dict:
    try:
        stats = os.statvfs(path)
        total = stats.f_frsize * stats.f_blocks
        free = stats.f_frsize * stats.f_bavail
        used = max(0, total - free)
        percent = round((used / total) * 100, 1) if total else None
        return {
            "id": identifier,
            "label": label,
            "status": "ready",
            "total_bytes": total,
            "used_bytes": used,
            "free_bytes": free,
            "used_percent": percent,
        }
    except OSError:
        return {
            "id": identifier,
            "label": label,
            "status": "unavailable",
            "total_bytes": None,
            "used_bytes": None,
            "free_bytes": None,
            "used_percent": None,
        }


def _domain_statuses(payload: dict) -> dict[str, str]:
    value = payload.get("domain_verify")
    if not isinstance(value, dict):
        return {}
    result = {}
    for key in ("ers", "hermes", "platform"):
        row = value.get(key)
        if isinstance(row, dict) and isinstance(row.get("status"), str):
            result[key] = row["status"]
    return result


def _backup(root: Path) -> dict:
    monitor = _read_json(root / "monitor.json")
    daily = _read_json(root / "daily.json")
    weekly = _read_json(root / "weekly.json")
    restore = weekly.get("restore_validation") if isinstance(weekly.get("restore_validation"), dict) else {}
    restore_knowledge = restore.get("knowledge") if isinstance(restore.get("knowledge"), dict) else {}
    restore_domains = restore.get("domains") if isinstance(restore.get("domains"), dict) else {}

    monitor_status = monitor.get("status") if isinstance(monitor.get("status"), str) else "UNKNOWN"
    issue_count = len(monitor.get("issues", [])) if isinstance(monitor.get("issues"), list) else 0
    return {
        "status": monitor_status,
        "monitor": {
            "status": monitor_status,
            "checked_at": monitor.get("checked_at"),
            "freshest_backup_age_hours": monitor.get("freshest_backup_age_hours"),
            "weekly_age_hours": monitor.get("weekly_age_hours"),
            "nas_free_bytes": monitor.get("nas_free_bytes"),
            "issue_count": issue_count,
        },
        "daily": {
            "status": daily.get("status", "UNKNOWN"),
            "completed_at": daily.get("completed_at"),
            "duration_seconds": daily.get("duration_seconds"),
            "knowledge_status": (daily.get("knowledge_verify") or {}).get("status") if isinstance(daily.get("knowledge_verify"), dict) else None,
            "ers_case_store_status": (daily.get("ers_case_store_verify") or {}).get("status") if isinstance(daily.get("ers_case_store_verify"), dict) else None,
            "wvc_status": (daily.get("wvc_verify") or {}).get("status") if isinstance(daily.get("wvc_verify"), dict) else None,
            "domain_statuses": _domain_statuses(daily),
            "retention_status": (daily.get("retention") or {}).get("status") if isinstance(daily.get("retention"), dict) else None,
            "secrets_automation": daily.get("secrets_automation"),
        },
        "weekly": {
            "status": weekly.get("status", "UNKNOWN"),
            "completed_at": weekly.get("completed_at"),
            "duration_seconds": weekly.get("duration_seconds"),
            "knowledge_status": (weekly.get("knowledge_verify") or {}).get("status") if isinstance(weekly.get("knowledge_verify"), dict) else None,
            "wvc_status": (weekly.get("wvc_verify") or {}).get("status") if isinstance(weekly.get("wvc_verify"), dict) else None,
            "domain_statuses": _domain_statuses(weekly),
            "retention_status": (weekly.get("retention") or {}).get("status") if isinstance(weekly.get("retention"), dict) else None,
            "restore_knowledge_status": restore_knowledge.get("status"),
            "restore_domains_status": restore_domains.get("status"),
            "secrets_automation": weekly.get("secrets_automation"),
        },
    }


def operations_snapshot(
    *,
    current_release: Path = _CURRENT_RELEASE,
    backup_status: Path = _BACKUP_STATUS,
    storage_targets: Iterable[tuple[str, str, Path]] | None = None,
) -> dict:
    targets = tuple(storage_targets or (
        ("system", "System", Path("/")),
        ("data", "AI data", Path("/srv/ai-data")),
    ))
    backup = _backup(backup_status)
    storage = [_disk(identifier, label, path) for identifier, label, path in targets]
    storage.append({
        "id": "globalnas",
        "label": "GlobalNAS",
        "status": "ready" if backup["monitor"]["status"] == "PASS" else "warning",
        "total_bytes": None,
        "used_bytes": None,
        "free_bytes": backup["monitor"].get("nas_free_bytes"),
        "used_percent": None,
    })
    return {
        "release": _release(current_release),
        "storage": storage,
        "backup": backup,
    }
