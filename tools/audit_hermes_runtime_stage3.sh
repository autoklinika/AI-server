#!/usr/bin/env bash
set -euo pipefail

ROOT="${HOME}/AI-server"
PYTHON="${PYTHON:-python3}"

section() {
    echo
    echo "===== $1 ====="
}

safe_cmd() {
    "$@" 2>/dev/null || true
}

redact_stream() {
    "$PYTHON" -c '
import re
import sys

SECRET_KEYS = re.compile(
    r"(?i)(token|api[_-]?key|secret|password|passwd|authorization|bearer|bot[_-]?token)"
)
ASSIGNMENT = re.compile(r"^\s*([^=:#]+)\s*[:=]\s*(.*)$")
URL_CREDS = re.compile(r"(https?://)([^/@\s:]+):([^/@\s]+)@")
BEARER = re.compile(r"(?i)bearer\s+[A-Za-z0-9._~+/=-]+")
LONG_TOKEN = re.compile(r"\b[A-Za-z0-9_-]{32,}\b")

for raw in sys.stdin:
    line = raw.rstrip("\n")
    line = URL_CREDS.sub(r"\1***:***@", line)
    line = BEARER.sub("Bearer ***", line)
    m = ASSIGNMENT.match(line)
    if m and SECRET_KEYS.search(m.group(1)):
        print(f"{m.group(1).strip()}=***REDACTED***")
        continue
    line = re.sub(r"\b\d{6,12}:[A-Za-z0-9_-]{20,}\b", "***TELEGRAM_TOKEN_REDACTED***", line)
    if SECRET_KEYS.search(line):
        line = LONG_TOKEN.sub("***REDACTED***", line)
    print(line)
'
}

section "HERMES RUNTIME AUDIT - READ ONLY"
echo "host:     $(hostname)"
echo "user:     $(id -un)"
echo "repo:     $ROOT"
echo "branch:   $(git -C "$ROOT" branch --show-current 2>/dev/null || echo unknown)"
echo "HEAD:     $(git -C "$ROOT" rev-parse HEAD 2>/dev/null || echo unknown)"
echo "gateway:  $(systemctl is-active ai-gateway.service 2>/dev/null || true)"
echo "ollama:   $(systemctl is-active ollama.service 2>/dev/null || true)"

section "SYSTEMD SYSTEM UNITS"
safe_cmd systemctl list-units --type=service --all --no-pager \
    | grep -Ei 'hermes|telegram|ollama|agent' \
    | redact_stream || true

section "SYSTEMD USER UNITS"
safe_cmd systemctl --user list-units --type=service --all --no-pager \
    | grep -Ei 'hermes|telegram|ollama|agent' \
    | redact_stream || true

section "SYSTEMD UNIT FILES"
{
    safe_cmd systemctl list-unit-files --type=service --no-pager
    safe_cmd systemctl --user list-unit-files --type=service --no-pager
} | grep -Ei 'hermes|telegram|agent' | sort -u | redact_stream || true

section "PROCESSES"
# Use /proc instead of GNU-specific ps switches so the audit works regardless of
# procps/busybox/localized ps option parsing.
"$PYTHON" - <<'PY' | redact_stream || true
from pathlib import Path
import os
import re

wanted = re.compile(r"(?i)(hermes|telegram|ollama|uvicorn|fastapi)")
for proc in sorted(Path("/proc").iterdir(), key=lambda p: int(p.name) if p.name.isdigit() else 10**9):
    if not proc.name.isdigit():
        continue
    try:
        cmdline = (proc / "cmdline").read_bytes().replace(b"\0", b" ").decode("utf-8", "replace").strip()
        if not cmdline or not wanted.search(cmdline):
            continue
        status = (proc / "status").read_text(encoding="utf-8", errors="replace")
        uid_line = next((line for line in status.splitlines() if line.startswith("Uid:")), "")
        ppid_line = next((line for line in status.splitlines() if line.startswith("PPid:")), "")
        uid = int(uid_line.split()[1]) if uid_line else -1
        try:
            import pwd
            user = pwd.getpwuid(uid).pw_name
        except Exception:
            user = str(uid)
        ppid = ppid_line.split()[1] if ppid_line else "?"
        print(f"{user}\tpid={proc.name}\tppid={ppid}\t{cmdline}")
    except (OSError, ValueError):
        continue
PY

section "CONTAINERS"
if command -v docker >/dev/null 2>&1; then
    safe_cmd docker ps --format 'docker\t{{.ID}}\t{{.Image}}\t{{.Names}}\t{{.Ports}}' \
        | grep -Ei 'hermes|telegram|agent|ollama' \
        | redact_stream || true
else
    echo "docker: not installed"
fi
if command -v podman >/dev/null 2>&1; then
    safe_cmd podman ps --format 'podman\t{{.ID}}\t{{.Image}}\t{{.Names}}\t{{.Ports}}' \
        | grep -Ei 'hermes|telegram|agent|ollama' \
        | redact_stream || true
else
    echo "podman: not installed"
fi

section "TMUX / SCREEN"
if command -v tmux >/dev/null 2>&1; then
    safe_cmd tmux list-sessions | redact_stream || true
else
    echo "tmux: not installed"
fi
if command -v screen >/dev/null 2>&1; then
    safe_cmd screen -ls | redact_stream || true
else
    echo "screen: not installed"
fi

section "LISTENING PORTS"
safe_cmd ss -ltnp \
    | grep -E '127\.0\.0\.1|0\.0\.0\.0|\[::\]' \
    | grep -E ':11434|:11435|:8000|:8080|:3000|:5000|:7860|:9000' \
    | redact_stream || true

section "HERMES COMMAND DISCOVERY"
FOUND_HERMES=0
for cmd in hermes hermes-agent hermes-agent-cli; do
    if command -v "$cmd" >/dev/null 2>&1; then
        FOUND_HERMES=1
        path="$(command -v "$cmd")"
        echo "$cmd: $path"
        echo "-- version/help probe --"
        { safe_cmd timeout 5s "$cmd" --version; safe_cmd timeout 5s "$cmd" version; } \
            | head -n 12 | redact_stream || true
    fi
done
[ "$FOUND_HERMES" -eq 1 ] || echo "No Hermes CLI found in PATH"

section "HERMES EXECUTABLE DETAILS"
if command -v hermes >/dev/null 2>&1; then
    HERMES_BIN="$(command -v hermes)"
    safe_cmd ls -l "$HERMES_BIN" | redact_stream || true
    safe_cmd readlink -f "$HERMES_BIN" | redact_stream || true
    if head -n 1 "$HERMES_BIN" 2>/dev/null | grep -q '^#!'; then
        head -n 3 "$HERMES_BIN" | redact_stream || true
    fi
fi

section "LIKELY HERMES PATHS"
CANDIDATES=(
    "$HOME/.hermes"
    "$HOME/.config/hermes"
    "$HOME/.local/share/hermes"
    "$HOME/hermes"
    "$HOME/Hermes"
    "/srv/ai-data/hermes"
    "/opt/hermes"
    "/etc/hermes"
)
for path in "${CANDIDATES[@]}"; do
    if [ -e "$path" ]; then
        if [ -d "$path" ]; then
            echo "DIR  $path"
            find "$path" -maxdepth 3 -type f -printf '  %p\n' 2>/dev/null \
                | head -n 180 \
                | redact_stream || true
        else
            echo "FILE $path"
        fi
    fi
done

section "RELEVANT SANITIZED CONFIG LINES"
"$PYTHON" - <<'PY'
from __future__ import annotations

from pathlib import Path
import re

roots = [
    Path.home() / ".hermes",
    Path.home() / ".config/hermes",
    Path.home() / ".local/share/hermes",
    Path.home() / "hermes",
    Path.home() / "Hermes",
    Path("/srv/ai-data/hermes"),
    Path("/opt/hermes"),
    Path("/etc/hermes"),
]

interesting_name = re.compile(r"(?i)(config|setting|provider|profile|telegram|gateway|env|yaml|yml|json|toml)")
interesting_line = re.compile(
    r"(?i)(ollama|openai|base[_-]?url|endpoint|provider|model|telegram|session|chat[_-]?id|"
    r"concurr|parallel|busy|queue|stream|memory|workspace|inference|api[_-]?base)"
)
secret_key = re.compile(r"(?i)(token|api[_-]?key|secret|password|passwd|authorization|bearer)")
assignment = re.compile(r"^(\s*[^=:#]+\s*[:=]\s*)(.*)$")
telegram_token = re.compile(r"\b\d{6,12}:[A-Za-z0-9_-]{20,}\b")
url_creds = re.compile(r"(https?://)([^/@\s:]+):([^/@\s]+)@")

seen = set()
files = []
for root in roots:
    if not root.exists() or not root.is_dir():
        continue
    for path in root.rglob("*"):
        if len(files) >= 300:
            break
        if not path.is_file() or path in seen:
            continue
        seen.add(path)
        if any(part.lower() in {"cache", ".git", "node_modules", ".venv", "venv", "models"} for part in path.parts):
            continue
        try:
            size = path.stat().st_size
        except OSError:
            continue
        if size > 512_000:
            continue
        if not (interesting_name.search(path.name) or path.suffix.lower() in {".env", ".json", ".yaml", ".yml", ".toml", ".ini", ".conf"}):
            continue
        files.append(path)

for path in files:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        continue
    matches = []
    for lineno, raw in enumerate(text.splitlines(), 1):
        if not interesting_line.search(raw):
            continue
        line = url_creds.sub(r"\1***:***@", raw)
        line = telegram_token.sub("***TELEGRAM_TOKEN_REDACTED***", line)
        m = assignment.match(line)
        if m and secret_key.search(m.group(1)):
            line = m.group(1) + "***REDACTED***"
        elif secret_key.search(line):
            line = "***REDACTED_SECRET_BEARING_LINE***"
        matches.append((lineno, line[:500]))
    if matches:
        print(f"--- {path}")
        for lineno, line in matches[:100]:
            print(f"{lineno}: {line}")
PY

section "HERMES PROCESS ENVIRONMENT (SANITIZED KEYS ONLY)"
"$PYTHON" - <<'PY'
from pathlib import Path
import re

wanted_process = re.compile(r"(?i)hermes")
wanted_key = re.compile(r"(?i)(ollama|openai|base.*url|endpoint|provider|model|telegram|session|concurr|parallel|queue|workspace|api.*base)")
secret_key = re.compile(r"(?i)(token|key|secret|password|passwd|authorization|bearer)")

for proc in Path("/proc").iterdir():
    if not proc.name.isdigit():
        continue
    try:
        cmd = (proc / "cmdline").read_bytes().replace(b"\0", b" ").decode("utf-8", "replace")
        if not wanted_process.search(cmd):
            continue
        env = (proc / "environ").read_bytes().split(b"\0")
    except OSError:
        continue
    print(f"--- pid={proc.name}")
    for item in env:
        if b"=" not in item:
            continue
        key_b, value_b = item.split(b"=", 1)
        key = key_b.decode("utf-8", "replace")
        if not wanted_key.search(key):
            continue
        if secret_key.search(key):
            value = "***REDACTED***"
        else:
            value = value_b.decode("utf-8", "replace")[:500]
        print(f"{key}={value}")
PY

section "RECENT HERMES-RELATED JOURNAL"
{
    safe_cmd journalctl --no-pager -n 200 -u hermes.service
    safe_cmd journalctl --user --no-pager -n 200 -u hermes.service
} | grep -Ei 'hermes|telegram|ollama|openai|provider|session|error|cuda|gpu' | redact_stream || true

section "AUDIT COMPLETE"
echo "READ-ONLY: no services, configs, routes or processes were modified."
echo "Secrets were redacted where detected. Review output before sharing externally."
