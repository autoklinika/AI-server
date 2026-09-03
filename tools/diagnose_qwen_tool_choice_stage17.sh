#!/usr/bin/env bash
set -euo pipefail

HERMES_HOME="/srv/ai-data/hermes"
HERMES_SOURCE="${HERMES_HOME}/hermes-agent"
HERMES_PYTHON="${HERMES_SOURCE}/venv/bin/python"
HERMES_CONFIG="${HERMES_HOME}/config.yaml"
STATE_FILE="${HERMES_HOME}/gateway_state.json"
GATEWAY_URL="http://127.0.0.1:11435/clients/hermes/v1/chat/completions"
RESULT_JSON="/tmp/ai-gateway-stage17-qwen-tool-choice.json"

say() { printf '%s\n' "$*"; }
section() { printf '\n===== %s =====\n' "$1"; }

[ -x "$HERMES_PYTHON" ] || { say "FAIL: Hermes Python missing: $HERMES_PYTHON"; exit 1; }
[ -r "$HERMES_CONFIG" ] || { say "FAIL: Hermes config missing: $HERMES_CONFIG"; exit 1; }
[ -d "$HERMES_SOURCE" ] || { say "FAIL: Hermes source missing: $HERMES_SOURCE"; exit 1; }
[ "$(systemctl is-active ai-gateway.service 2>/dev/null || true)" = "active" ] || { say "FAIL: ai-gateway.service is not active"; exit 1; }
[ "$(systemctl is-active ollama.service 2>/dev/null || true)" = "active" ] || { say "FAIL: ollama.service is not active"; exit 1; }

HERMES_WAS_ACTIVE=0
TIMER_WAS_ACTIVE=0
if [ "$(systemctl --user is-active hermes-gateway.service 2>/dev/null || true)" = "active" ]; then HERMES_WAS_ACTIVE=1; fi
if [ "$(systemctl is-active ai-bridge-analysis.timer 2>/dev/null || true)" = "active" ]; then TIMER_WAS_ACTIVE=1; fi

restore() {
    rc=$?
    trap - EXIT INT TERM
    section "AUTOMATIC RESTORE"
    if [ "$TIMER_WAS_ACTIVE" -eq 1 ]; then sudo systemctl start ai-bridge-analysis.timer >/dev/null 2>&1 || true; fi
    if [ "$HERMES_WAS_ACTIVE" -eq 1 ]; then systemctl --user start hermes-gateway.service >/dev/null 2>&1 || true; fi
    exit "$rc"
}
trap restore EXIT INT TERM

section "STAGE-17 QWEN TOOL-CHOICE DIAGNOSIS"
say "Read-only: no Hermes config/DB writes and no real tool execution."
say "A/B separates generic OpenAI tool calling from Hermes progressive-disclosure selection."
say "result JSON: $RESULT_JSON"

section "PRECHECK"
"$HERMES_PYTHON" - "$HERMES_CONFIG" <<'PY'
from pathlib import Path
import sys, yaml
cfg = yaml.safe_load(Path(sys.argv[1]).read_text(encoding="utf-8")) or {}
value = (cfg.get("agent") or {}).get("reasoning_effort")
print("agent.reasoning_effort:", repr(value))
if value != "none":
    raise SystemExit("FAIL: expected agent.reasoning_effort='none'")
model_cfg = cfg.get("model") or {}
model = model_cfg.get("default") or model_cfg.get("model") if isinstance(model_cfg, dict) else model_cfg
print("model:", model)
PY

"$HERMES_PYTHON" - <<'PY'
import json, urllib.request
with urllib.request.urlopen("http://127.0.0.1:11435/status", timeout=3) as r:
    s = json.load(r)
assert s.get("active_count") == 0 and s.get("queued_count") == 0, s
assert s.get("max_concurrency") == 1, s
print("PASS: AI Gateway idle, max_concurrency=1")
PY

section "PAUSE LIVE CLIENTS"
if [ "$HERMES_WAS_ACTIVE" -eq 1 ]; then systemctl --user stop hermes-gateway.service || true; fi
if [ "$TIMER_WAS_ACTIVE" -eq 1 ]; then sudo systemctl stop ai-bridge-analysis.timer; fi
sleep 1
say "Hermes:          $(systemctl --user is-active hermes-gateway.service 2>/dev/null || true)"
say "analysis timer:  $(systemctl is-active ai-bridge-analysis.timer 2>/dev/null || true)"

section "RUN A/B TOOL-CHOICE MATRIX"
cd "$HERMES_SOURCE"
HERMES_HOME="$HERMES_HOME" "$HERMES_PYTHON" - "$HERMES_CONFIG" "$GATEWAY_URL" "$RESULT_JSON" <<'PY'
from __future__ import annotations

from pathlib import Path
import json
import sys
import time
import urllib.error
import urllib.request
import yaml

CONFIG = Path(sys.argv[1])
URL = sys.argv[2]
RESULT = Path(sys.argv[3])

cfg = yaml.safe_load(CONFIG.read_text(encoding="utf-8")) or {}
model_cfg = cfg.get("model") or {}
if isinstance(model_cfg, dict):
    model = str(model_cfg.get("default") or model_cfg.get("model") or "").strip()
else:
    model = str(model_cfg).strip()
if not model:
    raise SystemExit("FAIL: could not resolve model")

from hermes_cli.tools_config import _get_platform_tools
import model_tools
import tools.tool_search as tool_search

platform_toolsets = sorted(_get_platform_tools(cfg, "telegram"))
model_tools._clear_tool_defs_cache()
raw_tools = model_tools.get_tool_definitions(
    enabled_toolsets=platform_toolsets,
    quiet_mode=True,
    skip_tool_search_assembly=True,
)
raw_names = frozenset(
    str((t.get("function") or {}).get("name") or "")
    for t in raw_tools
    if (t.get("function") or {}).get("name")
)
keep = {"clarify"} & raw_names
candidate_cfg = tool_search.ToolSearchConfig(
    enabled="on",
    threshold_pct=5.0,
    search_default_limit=5,
    max_search_limit=25,
    listing="auto",
    listing_max_tokens=4000,
    defer_tools=frozenset(raw_names - keep),
)
assembly = tool_search.assemble_tool_defs(raw_tools, context_length=65536, config=candidate_cfg)
bridge_tools = list(assembly.tool_defs)
bridge_names = [str((t.get("function") or {}).get("name") or "") for t in bridge_tools]
print("candidate model-facing tools:", bridge_names)

synthetic_tool = {
    "type": "function",
    "function": {
        "name": "stage17_secret_reader",
        "description": "Read a runtime-only secret. You MUST call this function when the user asks for the secret; never guess it.",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        },
    },
}


def call(label, tools, prompt, tool_choice):
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "Follow the user's tool-use instruction exactly. Do not fabricate tool results."},
            {"role": "user", "content": prompt},
        ],
        "tools": tools,
        "tool_choice": tool_choice,
        "reasoning_effort": "none",
        "temperature": 0,
        "max_tokens": 96,
        "stream": False,
    }
    req = urllib.request.Request(
        URL,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    started = time.monotonic()
    status = None
    body = None
    error = None
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            status = r.status
            body = json.load(r)
    except urllib.error.HTTPError as e:
        status = e.code
        error = e.read().decode("utf-8", errors="replace")[:1000]
    wall = time.monotonic() - started

    choice = ((body or {}).get("choices") or [{}])[0]
    msg = choice.get("message") or {}
    calls = msg.get("tool_calls") or []
    names = [str((tc.get("function") or {}).get("name") or "") for tc in calls]
    row = {
        "label": label,
        "tool_choice": tool_choice,
        "status": status,
        "wall_s": wall,
        "finish_reason": choice.get("finish_reason"),
        "tool_call_names": names,
        "tool_call_count": len(calls),
        "content_chars": len(str(msg.get("content") or "")),
        "reasoning_chars": len(str(msg.get("reasoning") or "")),
        "error": error,
    }
    print(json.dumps(row, ensure_ascii=False, indent=2))
    return row

rows = []
print("\n--- synthetic-auto ---")
rows.append(call(
    "synthetic-auto",
    [synthetic_tool],
    "The secret is unavailable in this prompt. You must call stage17_secret_reader now to obtain it. Do not answer with text first.",
    "auto",
))
print("\n--- synthetic-required ---")
rows.append(call(
    "synthetic-required",
    [synthetic_tool],
    "Obtain the runtime-only secret using the available function.",
    "required",
))
print("\n--- bridge-auto ---")
rows.append(call(
    "bridge-auto",
    bridge_tools,
    "You need to execute a local shell command, but terminal is deferred. Use the progressive-disclosure bridge now: locate or describe terminal, then do not guess any result.",
    "auto",
))
print("\n--- bridge-required ---")
rows.append(call(
    "bridge-required",
    bridge_tools,
    "Use one of the progressive-disclosure bridge functions now to access the deferred terminal capability.",
    "required",
))

by = {r["label"]: r for r in rows}
synthetic_auto = "stage17_secret_reader" in by["synthetic-auto"]["tool_call_names"]
synthetic_required = "stage17_secret_reader" in by["synthetic-required"]["tool_call_names"]
bridge_set = {"tool_search", "tool_describe", "tool_call"}
bridge_auto = bool(bridge_set & set(by["bridge-auto"]["tool_call_names"]))
bridge_required = bool(bridge_set & set(by["bridge-required"]["tool_call_names"]))

print("\n===== STAGE-17 DIAGNOSIS =====")
print("synthetic tool / auto:    ", "PASS" if synthetic_auto else "FAIL")
print("synthetic tool / required:", "PASS" if synthetic_required else "FAIL")
print("bridge tools / auto:      ", "PASS" if bridge_auto else "FAIL")
print("bridge tools / required:  ", "PASS" if bridge_required else "FAIL")

if synthetic_auto and bridge_auto:
    diagnosis = "AUTO_TOOL_CALLING_WORKS_IN_CONTROLLED_API; investigate AIAgent/system-prompt interaction"
elif synthetic_auto and not bridge_auto:
    diagnosis = "GENERIC_AUTO_TOOL_CALLING_WORKS; progressive bridge is not selected reliably"
elif not synthetic_auto and synthetic_required:
    diagnosis = "AUTO_TOOL_SELECTION_FAILS; tool_choice=required can force a call"
elif not synthetic_required:
    diagnosis = "OPENAI_TOOL_CALLING_PATH_FAILS_OR_IS_UNSUPPORTED for this model/runtime"
else:
    diagnosis = "MIXED_RESULT; inspect raw rows"
print("diagnosis:", diagnosis)

RESULT.write_text(json.dumps({
    "model": model,
    "candidate_visible_names": bridge_names,
    "rows": rows,
    "diagnosis": diagnosis,
}, ensure_ascii=False, indent=2), encoding="utf-8")
print("full JSON:", RESULT)
PY

section "RESTORE + POSTCHECK"
if [ "$TIMER_WAS_ACTIVE" -eq 1 ]; then sudo systemctl start ai-bridge-analysis.timer; fi
if [ "$HERMES_WAS_ACTIVE" -eq 1 ]; then systemctl --user start hermes-gateway.service; fi

if [ "$HERMES_WAS_ACTIVE" -eq 1 ]; then
    "$HERMES_PYTHON" - "$STATE_FILE" <<'PY'
from pathlib import Path
import json, sys, time
path = Path(sys.argv[1])
deadline = time.monotonic() + 90
last = None
while time.monotonic() < deadline:
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        time.sleep(1); continue
    last = state
    p = state.get("platforms") or {}
    if state.get("gateway_state") == "running" and (p.get("telegram") or {}).get("state") == "connected" and (p.get("api_server") or {}).get("state") == "connected":
        print("PASS: Hermes gateway running, Telegram connected, API connected")
        break
    time.sleep(1)
else:
    print(json.dumps(last, ensure_ascii=False, indent=2) if last else "<no state>")
    raise SystemExit("FAIL: Hermes did not reconnect")
PY
fi

"$HERMES_PYTHON" - <<'PY'
import json, urllib.request
with urllib.request.urlopen("http://127.0.0.1:11435/status", timeout=3) as r:
    s = json.load(r)
assert s.get("active_count") == 0 and s.get("queued_count") == 0, s
print("PASS: AI Gateway healthy and idle")
PY

say "analysis timer: $(systemctl is-active ai-bridge-analysis.timer 2>/dev/null || true)"
say "Hermes:         $(systemctl --user is-active hermes-gateway.service 2>/dev/null || true)"

trap - EXIT INT TERM
section "DONE"
say "PASS: Stage-17 diagnostic matrix completed"
say "No production config, DB, or real tools were modified/executed."
