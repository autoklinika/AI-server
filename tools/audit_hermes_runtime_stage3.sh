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
    "$PYTHON" - <<'PY'
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
    # Telegram bot tokens have a recognizable numeric-prefix form.
    line = re.sub(r"\b\d{6,12}:[A-Za-z0-9_-]{20,}\b", "***TELEGRAM_TOKEN_REDACTED***", line)
    if SECRET_KEYS.search(line):
        line = LONG_TOKEN.sub("***REDACTED***", line)
    print(line)
PY
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
ps -eo user,pid,ppid,lstart,args --ww \
    | grep -Ei '[h]ermes|[t]elegram|[o]llama|[u]vicorn|[f]astapi' \
    | redact_stream || true

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
    safe_cmd tmux list-sessions | redact_stream
else
    echo "tmux: not installed"
fi
if command -v screen >/dev/null 2>&1; then
    safe_cmd screen -ls | redact_stream
else
    echo "screen: not installed"
fi

section "LISTENING PORTS"
safe_cmd ss -ltnp \
    | grep -E '127\.0\.0\.1|0\.0\.0\.0|\[::\]' \
    | grep -E ':11434|:11435|:8000|:8080|:3000|:5000|:7860|:9000' \
    | redact_stream || true

section "HERMES COMMAND DISCOVERY"
for cmd in hermes hermes-agent hermes-agent-cli; do
    if command -v "$cmd" >/dev/null 2>&1; then
        path="$(command -v "$cmd")"
        echo "$cmd: $path"
        safe_cmd "$cmd" --version | head -n 5 | redact_stream
    fi
done

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
            find "$path" -maxdepth 2 -type f -printf '  %p\n' 2>/dev/null \
                | head -n 120 \
                | redact_stream
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

interesting_name = re.compile(r"(?i)(config|setting|provider|profile|telegram|gateway|env|yaml|yml|json|toml)$")
interesting_line = re.compile(
    r"(?i)(ollama|openai|base[_-]?url|endpoint|provider|model|telegram|session|chat[_-]?id|"
    r"concurr|parallel|busy|queue|stream|memory|workspace)"
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
        if len(files) >= 250:
            break
        if not path.is_file() or path in seen:
            continue
        seen.add(path)
        # Avoid caches, models, databases and large files.
        if any(part.lower() in {"cache", ".git", "node_modules", ".venv", "venv"} for part in path.parts):
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
            # Do not risk printing a secret-bearing free-form line.
            line = "***REDACTED_SECRET_BEARING_LINE***"
        matches.append((lineno, line[:500]))
    if matches:
        print(f"--- {path}")
        for lineno, line in matches[:80]:
            print(f"{lineno}: {line}")
PY

section "RECENT HERMES-RELATED JOURNAL"
{
    safe_cmd journalctl --no-pager -n 150 -u hermes.service
    safe_cmd journalctl --user --no-pager -n 150 -u hermes.service
} | grep -Ei 'hermes|telegram|ollama|openai|provider|session|error|cuda|gpu' | redact_stream || true

section "AUDIT COMPLETE"
echo "READ-ONLY: no services, configs, routes or processes were modified."
echo "Secrets were redacted where detected. Review output before sharing externally."
