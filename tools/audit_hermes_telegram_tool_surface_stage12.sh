#!/usr/bin/env bash
set -euo pipefail

HERMES_HOME="/srv/ai-data/hermes"
HERMES_SOURCE="${HERMES_HOME}/hermes-agent"
HERMES_CONFIG="${HERMES_HOME}/config.yaml"
HERMES_PYTHON="${HERMES_SOURCE}/venv/bin/python"

say() { printf '%s\n' "$*"; }
section() { printf '\n===== %s =====\n' "$1"; }

[ -x "$HERMES_PYTHON" ] || { say "FAIL: Hermes Python missing: $HERMES_PYTHON"; exit 1; }
[ -r "$HERMES_CONFIG" ] || { say "FAIL: Hermes config missing: $HERMES_CONFIG"; exit 1; }
[ -d "$HERMES_SOURCE" ] || { say "FAIL: Hermes source missing: $HERMES_SOURCE"; exit 1; }

section "STAGE-12 HERMES TELEGRAM TOOL-SURFACE AUDIT"
say "Read-only: no config writes, no DB writes, no service restarts, no inference."
say "This measures tool schema overhead exposed to the model."

HERMES_HOME="$HERMES_HOME" "$HERMES_PYTHON" - "$HERMES_CONFIG" "$HERMES_SOURCE" <<'PY'
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import yaml

config_path = Path(sys.argv[1])
source = Path(sys.argv[2])
sys.path.insert(0, str(source))
os.environ["HERMES_HOME"] = str(config_path.parent)

cfg = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
platform_toolsets = cfg.get("platform_toolsets") or {}
telegram_sets = platform_toolsets.get("telegram")
if telegram_sets is None:
    telegram_sets = ["hermes-telegram"]
if isinstance(telegram_sets, str):
    telegram_sets = [telegram_sets]
if not isinstance(telegram_sets, list):
    raise SystemExit(f"FAIL: platform_toolsets.telegram is not a list/string: {telegram_sets!r}")
telegram_sets = [str(x).strip() for x in telegram_sets if str(x).strip()]

from toolsets import resolve_toolset

resolved = []
for name in telegram_sets:
    for tool in resolve_toolset(name):
        if tool not in resolved:
            resolved.append(tool)

print("configured Telegram toolsets:", telegram_sets)
print("resolved Telegram tool names:", len(resolved))
print("resolved names:", ", ".join(resolved))

# Import the same schema provider used by Hermes agent turns. This is read-only;
# availability probes may inspect local binaries/services but do not alter config.
from model_tools import get_tool_definitions


def compact_chars(defs):
    return len(json.dumps(defs, ensure_ascii=False, separators=(",", ":")))


def summarize(label: str, enabled: list[str]):
    public_defs = get_tool_definitions(
        enabled_toolsets=enabled,
        disabled_toolsets=None,
        quiet_mode=True,
        skip_tool_search_assembly=False,
    )
    raw_defs = get_tool_definitions(
        enabled_toolsets=enabled,
        disabled_toolsets=None,
        quiet_mode=True,
        skip_tool_search_assembly=True,
    )
    print(f"\n[{label}]")
    print("toolsets:", enabled)
    print("API-visible definitions:", len(public_defs))
    print("API-visible schema chars:", compact_chars(public_defs))
    print("pre-assembly definitions:", len(raw_defs))
    print("pre-assembly schema chars:", compact_chars(raw_defs))
    return public_defs, raw_defs

current_public, current_raw = summarize("CURRENT TELEGRAM", telegram_sets)

rows = []
for item in current_raw:
    fn = item.get("function") or {}
    name = str(fn.get("name") or "<unnamed>")
    chars = len(json.dumps(item, ensure_ascii=False, separators=(",", ":")))
    rows.append((chars, name))
rows.sort(reverse=True)
print("\nLargest raw tool schemas:")
for chars, name in rows[:20]:
    print(f"  {chars:6d} chars  {name}")

# Comparison only. These profiles are NOT written anywhere and are not a
# recommendation by themselves; they quantify what a narrower Telegram tool
# surface would save if we decide to tune it later.
candidates = [
    ("NO TOOLS", []),
    ("CORE LOCAL", ["terminal", "file", "skills", "todo"]),
    ("CORE + WEB", ["terminal", "file", "web", "skills", "todo"]),
    ("RESEARCH", ["web", "file", "skills", "todo"]),
]
for label, sets in candidates:
    try:
        summarize(label, sets)
    except Exception as exc:
        print(f"\n[{label}] unavailable: {type(exc).__name__}: {exc}")

# Stored prompt sizes and single-call baselines anchor the static-schema numbers
# to what the installed runtime has actually reported in production.
import sqlite3

db_path = config_path.parent / "state.db"
if db_path.exists():
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        prompt_lengths = [r[0] for r in con.execute(
            "SELECT length(prompt) FROM system_prompts ORDER BY length(prompt) DESC LIMIT 5"
        ).fetchall()]
        print("\nstored system prompt char lengths (largest 5):", prompt_lengths)

        rows = con.execute(
            "SELECT s.source, u.session_id, u.api_call_count, u.input_tokens, u.output_tokens "
            "FROM session_model_usage u JOIN sessions s ON s.id=u.session_id "
            "WHERE u.api_call_count=1 ORDER BY u.last_seen DESC LIMIT 10"
        ).fetchall()
        print("single-API-call production baselines:")
        for r in rows:
            print({k: r[k] for k in r.keys()})
    finally:
        con.close()
PY

section "POSTCHECK"
echo "Hermes:  $(systemctl --user is-active hermes-gateway.service 2>/dev/null || true)"
echo "Gateway: $(systemctl is-active ai-gateway.service 2>/dev/null || true)"
echo "Ollama:  $(systemctl is-active ollama.service 2>/dev/null || true)"

say "PASS: Stage-12 read-only Hermes Telegram tool-surface audit completed"
