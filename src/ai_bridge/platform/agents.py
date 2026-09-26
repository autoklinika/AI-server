"""Read-only projection of bounded AI Platform agent/autopilot state.

Only allowlisted status files are inspected. Prompts, logs, reasons, tokens and
arbitrary paths are never exposed.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import re

_SOURCES = (
    ("autopilot-eh", "E-H Autopilot", "supervisor", "stage-eh/master.status", "status"),
    ("stage-e", "Stage E", "stage", "stage-eh/stage-E/status", "status"),
    ("stage-i", "Stage I", "stage", "stage-i/status", "status"),
    ("stage-j-production", "Stage J Production", "production-gate",
     "stage-j-production/progress", "progress"),
    ("manual-eh", "Manual E-H Recovery", "recovery", "manual-eh/status", "status"),
    ("stage-dh-master", "Stage D-H Master", "supervisor",
     "stage-dh-master/master.status", "status"),
)

_STATE = re.compile(r"^[A-Z0-9][A-Z0-9:_-]{0,63}$")
_STEP = re.compile(r"^(?:PRODUCTION:)?[0-9]{2}_[A-Za-z0-9_.-]+\.sh$")
_STAGE = re.compile(r"(?:^|\s)stage=([A-Z])(?:\s|$)")


def _safe_state(value: str) -> str:
    return value if _STATE.fullmatch(value) else "UNKNOWN"


def _parse_status(line: str, mode: str) -> tuple[str, str | None, str | None]:
    value = line.strip()
    if not value:
        return "UNKNOWN", None, None

    if mode == "progress":
        step = value if _STEP.fullmatch(value) else None
        return ("LAST_STEP" if step else "UNKNOWN"), step, None

    first = value.split()[0]
    stage_match = _STAGE.search(value)
    stage = stage_match.group(1) if stage_match else None

    if first.startswith("STATE="):
        return _safe_state(first.split("=", 1)[1]), None, stage
    if first.startswith("PRODUCTION:"):
        step = first.split(":", 1)[1]
        return "PRODUCTION", step if _STEP.fullmatch(step) else None, stage
    return _safe_state(first), None, stage


def agents_snapshot(root: Path | None = None) -> dict[str, object]:
    base = root or (Path.home() / "agent-state")
    now = datetime.now(timezone.utc)
    agents = []

    for agent_id, label, kind, relative, mode in _SOURCES:
        path = base / relative
        try:
            stat = path.stat()
            line = path.read_text(encoding="utf-8", errors="replace").splitlines()[0]
        except (OSError, IndexError):
            continue

        state, step, stage = _parse_status(line, mode)
        updated = datetime.fromtimestamp(stat.st_mtime, timezone.utc)
        age_seconds = max(0, int((now - updated).total_seconds()))
        terminal = state == "COMPLETE" or state.startswith("BLOCKED")
        agents.append({
            "agent_id": agent_id,
            "label": label,
            "kind": kind,
            "state": state,
            "step": step,
            "stage": stage,
            "updated_at": updated.isoformat(),
            "age_seconds": age_seconds,
            "freshness": "recent" if age_seconds <= 3600 else "historical",
            "terminal": terminal,
        })

    agents.sort(key=lambda item: item["updated_at"], reverse=True)
    return {
        "agents": agents,
        "retention": {
            "persistent": True,
            "source": "bounded-status-files",
            "raw_logs_exposed": False,
        },
    }
