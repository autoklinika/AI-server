#!/usr/bin/env python3
"""Read one explicitly tagged test request; never send, render, import Hermes or write state."""
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path

MAX_FILE_BYTES = 512 * 1024
MAX_JOBS = 500
ID = re.compile(r"-?[1-9][0-9]*")
TARGET = re.compile(r"telegram:(-?[1-9][0-9]*)(?::([1-9][0-9]*))?")


def load_record(path: Path) -> dict | None:
    try:
        if path.is_symlink() or path.stat().st_size > MAX_FILE_BYTES:
            return None
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else None
    except (OSError, UnicodeError, ValueError):
        return None


def routing_labels(home: Path) -> tuple[dict[str, str], str]:
    """Only numeric home/allowlist values are retained; no credentials are returned."""
    try:
        from dotenv import dotenv_values
        config = dotenv_values(home / ".env", interpolate=False)
    except Exception:
        return {}, "unavailable"
    labels: dict[str, str] = {}
    home_id = str(config.get("TELEGRAM_HOME_CHANNEL") or "").strip()
    if ID.fullmatch(home_id):
        labels[home_id] = "HOME_CHANNEL"
    allowed = str(config.get("TELEGRAM_ALLOWED_USERS") or "")
    for value in re.findall(r"(?<![\w])-?[1-9][0-9]*(?![\w])", allowed):
        if value not in labels:
            labels[value] = f"OTHER_ALLOWED_{1 + sum(v.startswith('OTHER_ALLOWED_') for v in labels.values())}"
    return labels, "read" if labels else "no_numeric_routes"


def route_summary(value: object, labels: dict[str, str]) -> dict:
    match = TARGET.fullmatch(value.strip()) if isinstance(value, str) else None
    if not match:
        return {"recipient": "unset_or_invalid", "topic_present": False}
    return {"recipient": labels.get(match[1], "OTHER_CHAT"), "topic_present": bool(match[2])}


def safe_time(value: object) -> str | None:
    try:
        if type(value) in (int, float):
            parsed = datetime.fromtimestamp(value, timezone.utc)
        elif isinstance(value, str):
            parsed = datetime.fromisoformat(value)
            if parsed.tzinfo is None:
                return None
        else:
            return None
        return parsed.astimezone(timezone.utc).isoformat()
    except (ValueError, OverflowError, OSError):
        return None


def inspect(jobs_root: Path, tag: str, labels: dict[str, str]) -> dict:
    if not re.fullmatch(r"[A-Z][A-Z0-9_]{7,79}", tag):
        raise ValueError("Tag must be 8-80 uppercase ASCII letters, digits or underscores.")
    pattern = re.compile(r"(?<![A-Za-z0-9_])" + re.escape(tag) + r"(?![A-Za-z0-9_])")
    report = {"tag": tag, "matches": [], "scan": {}}
    for kind, directory in (("foto", "hermes-foto-jobs"), ("wideo", "hermes-video-jobs")):
        root = jobs_root / directory
        scan = {"root_available": root.is_dir(), "scanned": 0, "unreadable_records": 0, "truncated": False}
        candidates = []
        try:
            for path in root.glob("*/request.json"):
                try:
                    if path.parent.is_symlink():
                        continue
                    candidates.append((path.stat().st_mtime, path))
                except OSError:
                    scan["unreadable_records"] += 1
        except OSError:
            scan["root_available"] = False
        candidates.sort(key=lambda item: item[0], reverse=True)
        scan["truncated"] = len(candidates) > MAX_JOBS
        for _, path in candidates[:MAX_JOBS]:
            scan["scanned"] += 1
            request = load_record(path)
            if request is None:
                scan["unreadable_records"] += 1
                continue
            prompt = request.get("prompt")
            if not isinstance(prompt, str) or not pattern.search(prompt):
                continue
            result_path = path.parent / "result.json"
            result = load_record(result_path)
            result_state = "readable" if result is not None else ("unreadable" if result_path.exists() else "not_yet_present")
            result = result or {}
            mode = request.get("mode")
            report["matches"].append({
                "kind": kind,
                "created_at_utc": safe_time(request.get("created_at")),
                "request_route": route_summary(request.get("target"), labels),
                "mode": mode if mode in ("generate", "edit", "t2v", "i2v") else "unspecified",
                "result_state": result_state,
                "result_route": route_summary(result.get("target"), labels),
                "request_result_same_target": request.get("target") == result.get("target") if result.get("target") else None,
                "worker_reported_ok": result.get("ok") if type(result.get("ok")) is bool else None,
                "has_error": bool(result.get("error")),
            })
        report["scan"][kind] = scan
    report["match_count"] = len(report["matches"])
    report["limitations"] = [
        "No match is not proof the bot did not receive the command; check its immediate reply.",
        "Recipient labels use the numeric .env configuration, not the gateway's live authorization policy.",
        "A saved result target is not a Telegram delivery receipt.",
    ]
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--home", type=Path, default=Path("/srv/ai-data/hermes"))
    parser.add_argument("--jobs", type=Path, default=Path("/srv/ai-data"))
    args = parser.parse_args()
    labels, state = routing_labels(args.home)
    try:
        result = inspect(args.jobs, args.tag, labels)
    except ValueError as exc:
        parser.error(str(exc))
    result["route_configuration"] = state
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
