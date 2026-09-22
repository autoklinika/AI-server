#!/usr/bin/env python3
"""Discover Telegram chat IDs already observed by Hermes without consuming bot updates."""
from __future__ import annotations

import json
import re
import subprocess
import sys
import urllib.parse
import urllib.request
from pathlib import Path

HERMES_ENV = Path("/srv/ai-data/hermes/.env")
JOB_ROOTS = (
    Path("/srv/ai-data/hermes-foto-jobs"),
    Path("/srv/ai-data/hermes-video-jobs"),
    Path("/srv/ai-data/hermes-wideo-jobs"),
)
TARGET_RE = re.compile(r"\btelegram:(-?\d{5,})\b")
SESSION_RE = re.compile(r"HERMES_SESSION_CHAT_ID[=: ]+['\"]?(-?\d{5,})")


def load_token() -> str:
    if not HERMES_ENV.is_file():
        return ""
    for raw in HERMES_ENV.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip() != "TELEGRAM_BOT_TOKEN":
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        return value
    return ""


def extract_ids(text: str) -> set[str]:
    ids = set(TARGET_RE.findall(text))
    ids.update(SESSION_RE.findall(text))
    return ids


def scan_jobs() -> set[str]:
    found: set[str] = set()
    for root in JOB_ROOTS:
        if not root.is_dir():
            continue
        for path in root.glob("*/request.json"):
            try:
                found.update(extract_ids(path.read_text(encoding="utf-8")))
            except (OSError, UnicodeError):
                continue
    return found


def scan_journal() -> set[str]:
    try:
        proc = subprocess.run(
            [
                "journalctl",
                "--user",
                "-u",
                "hermes-gateway.service",
                "--since",
                "30 days ago",
                "-o",
                "cat",
                "--no-pager",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=20,
            check=False,
        )
    except Exception:
        return set()
    return extract_ids(proc.stdout or "")


def get_chat(token: str, chat_id: str) -> dict:
    payload = urllib.parse.urlencode({"chat_id": chat_id}).encode("utf-8")
    url = f"https://api.telegram.org/bot{token}/getChat"
    request = urllib.request.Request(url, data=payload, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            body = json.loads(response.read().decode("utf-8"))
    except Exception:
        return {}
    result = body.get("result")
    return result if isinstance(result, dict) else {}


def main() -> int:
    token = load_token()
    if not token:
        print("FAIL: TELEGRAM_BOT_TOKEN not found in /srv/ai-data/hermes/.env", file=sys.stderr)
        return 2

    ids = scan_jobs() | scan_journal()
    if not ids:
        print("No Telegram chat IDs found in existing Hermes jobs/journal.")
        print("Send one normal message to the Hermes Telegram bot and run this helper again.")
        return 3

    print("Known Telegram chats:")
    for chat_id in sorted(ids, key=lambda value: int(value)):
        chat = get_chat(token, chat_id)
        username = chat.get("username") or "-"
        first_name = chat.get("first_name") or ""
        last_name = chat.get("last_name") or ""
        title = chat.get("title") or ""
        label = " ".join(part for part in (first_name, last_name) if part).strip() or title or "-"
        print(f"{chat_id}\t@{username}\t{label}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
