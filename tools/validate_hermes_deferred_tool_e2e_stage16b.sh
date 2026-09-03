#!/usr/bin/env bash
set -euo pipefail

PROD_HERMES_HOME="/srv/ai-data/hermes"
HERMES_SOURCE="${PROD_HERMES_HOME}/hermes-agent"
HERMES_PYTHON="${HERMES_SOURCE}/venv/bin/python"
HERMES_CONFIG="${PROD_HERMES_HOME}/config.yaml"
STATE_FILE="${PROD_HERMES_HOME}/gateway_state.json"
RESULT_JSON="/tmp/ai-gateway-stage16b-deferred-tool-e2e.json"
TMP_ROOT="$(mktemp -d /tmp/ai-gateway-stage16b.XXXXXX)"

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
    rm -rf "$TMP_ROOT"
    exit "$rc"
}
trap restore EXIT INT TERM

section "STAGE-16B DEFERRED TOOL END-TO-END VALIDATION"
say "Candidate: full Telegram toolset + defer-all-except-clarify."
say "No production Hermes config or DB writes."
say "The terminal handler is replaced inside this isolated process by a safe stub."
say "The stub returns a runtime-random secret that is NEVER placed in the model prompt."
say "result JSON: $RESULT_JSON"

section "PRECHECK"
"$HERMES_PYTHON" - "$HERMES_CONFIG" <<'PY'
from pathlib import Path
import sys, yaml
cfg = yaml.safe_load(Path(sys.argv[1]).read_text(encoding="utf-8")) or {}
value = (cfg.get("agent") or {}).get("reasoning_effort")
print("agent.reasoning_effort:", repr(value))
if value != "none":
    raise SystemExit("FAIL: expected literal agent.reasoning_effort='none'")
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

"$HERMES_PYTHON" - <<'PY'
import json, time, urllib.request
for _ in range(100):
    with urllib.request.urlopen("http://127.0.0.1:11435/status", timeout=3) as r:
        s = json.load(r)
    if s.get("active_count") == 0 and s.get("queued_count") == 0:
        print("PASS: AI Gateway idle after client pause")
        break
    time.sleep(0.1)
else:
    raise SystemExit(f"FAIL: gateway did not become idle: {s}")
PY

section "RUN ISOLATED HERMES AGENT WITH DEFERRED TERMINAL"
mkdir -p "$TMP_ROOT/hermes" "$TMP_ROOT/workspace"
cd "$HERMES_SOURCE"

HERMES_HOME="$TMP_ROOT/hermes" TERMINAL_CWD="$TMP_ROOT/workspace" \
"$HERMES_PYTHON" - "$HERMES_CONFIG" "$RESULT_JSON" <<'PY'
from __future__ import annotations

from pathlib import Path
import json
import os
import secrets
import sys
import time
import yaml

PROD_CONFIG = Path(sys.argv[1])
RESULT_PATH = Path(sys.argv[2])
GATEWAY_BASE = "http://127.0.0.1:11435/clients/hermes/v1"
EXPECTED_COMMAND = "cat /tmp/stage16b-runtime-secret"
# Critical invariant: this value is created at runtime and is not interpolated
# into any model-visible prompt/system text.
RUNTIME_SECRET = "S16B_" + secrets.token_hex(12).upper()

cfg = yaml.safe_load(PROD_CONFIG.read_text(encoding="utf-8")) or {}
model_cfg = cfg.get("model") or {}
if isinstance(model_cfg, dict):
    model = str(model_cfg.get("default") or model_cfg.get("model") or "").strip()
else:
    model = str(model_cfg).strip()
if not model:
    raise SystemExit("FAIL: could not resolve Hermes model")

platform_toolsets = cfg.get("platform_toolsets") or {}
configured = platform_toolsets.get("telegram") if isinstance(platform_toolsets, dict) else None
if isinstance(configured, str):
    current_toolsets = [configured]
elif isinstance(configured, list) and configured:
    current_toolsets = [str(x) for x in configured if str(x).strip()]
else:
    current_toolsets = ["hermes-telegram"]

Path(os.environ["HERMES_HOME"]).mkdir(parents=True, exist_ok=True)
Path(os.environ["HERMES_HOME"], "config.yaml").write_text(
    "model:\n  provider: custom\n  default: " + json.dumps(model) + "\n"
    "  base_url: " + json.dumps(GATEWAY_BASE) + "\n"
    "agent:\n  reasoning_effort: none\n",
    encoding="utf-8",
)

import model_tools
import tools.tool_search as tool_search
from tools.registry import registry

model_tools._clear_tool_defs_cache()
raw_tools = model_tools.get_tool_definitions(
    enabled_toolsets=current_toolsets,
    quiet_mode=True,
    skip_tool_search_assembly=True,
)
raw_names = frozenset(
    str((tool.get("function") or {}).get("name") or "")
    for tool in raw_tools
    if (tool.get("function") or {}).get("name")
)
if "terminal" not in raw_names:
    raise SystemExit(f"FAIL: terminal is not in raw Telegram tools: {sorted(raw_names)}")

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
original_load_config = tool_search.load_config
tool_search.load_config = lambda: candidate_cfg
model_tools._clear_tool_defs_cache()

terminal_entry = registry.get_entry("terminal")
if terminal_entry is None:
    raise SystemExit("FAIL: terminal registry entry missing")
original_terminal_handler = terminal_entry.handler
original_terminal_check = terminal_entry.check_fn
terminal_calls = []

def safe_terminal_stub(args, **kwargs):
    args = args if isinstance(args, dict) else {}
    terminal_calls.append(args)
    command = str(args.get("command") or "").strip()
    if command != EXPECTED_COMMAND:
        return json.dumps({
            "success": False,
            "error": "stage16b safety stub rejected unexpected command",
            "received_command": command,
            "expected_command": EXPECTED_COMMAND,
        })
    return json.dumps({"success": True, "stdout": RUNTIME_SECRET + "\n", "exit_code": 0})

terminal_entry.handler = safe_terminal_stub
terminal_entry.check_fn = None

from run_agent import AIAgent

agent = None
convo = None
started = time.monotonic()
try:
    agent = AIAgent(
        base_url=GATEWAY_BASE,
        api_key="stage16b-local",
        provider="custom",
        api_mode="chat_completions",
        model=model,
        quiet_mode=True,
        platform="telegram",
        enabled_toolsets=current_toolsets,
        reasoning_config={"enabled": False},
        max_tokens=256,
        max_iterations=10,
        save_trajectories=False,
        skip_context_files=True,
        skip_memory=True,
        skip_background_review=True,
    )

    visible_names = sorted(
        str((tool.get("function") or {}).get("name") or "")
        for tool in (getattr(agent, "tools", None) or [])
        if (tool.get("function") or {}).get("name")
    )
    print("visible model-facing tools:", visible_names)
    expected_visible = {"tool_search", "tool_describe", "tool_call"} | keep
    missing = sorted(expected_visible - set(visible_names))
    if missing:
        raise SystemExit(f"FAIL: candidate missing bridge/eager tools: {missing}")
    if "terminal" in visible_names:
        raise SystemExit("FAIL: terminal should be deferred, but is directly visible")

    prompt = (
        "This is an execution-verification task. The required value is unknown to you and exists only behind a local tool result. "
        "You MUST use the progressive-disclosure bridge to access the deferred terminal tool. "
        "Discover/describe the terminal tool as needed, then invoke it through tool_call with exactly this shell command: "
        + EXPECTED_COMMAND
        + ". Do not infer or invent the command output. After the tool returns, reply with ONLY the exact stdout value, with no quotes, label, or explanation. "
        "Do not use web, files, Python/code execution, clarify, or any other tool."
    )
    convo = agent.run_conversation(prompt)
    wall_s = time.monotonic() - started
finally:
    terminal_entry.handler = original_terminal_handler
    terminal_entry.check_fn = original_terminal_check
    tool_search.load_config = original_load_config
    model_tools._clear_tool_defs_cache()

messages = (convo or {}).get("messages") or getattr(agent, "messages", []) or []
bridge_calls = []
underlying_tool_calls = []
tool_result_secret_seen = False
api_turns = 0

for msg in messages:
    if msg.get("role") == "assistant":
        api_turns += 1
        for tc in msg.get("tool_calls") or []:
            fn = tc.get("function") or {}
            name = str(fn.get("name") or "")
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except Exception:
                args = {}
            if name in {"tool_search", "tool_describe", "tool_call"}:
                bridge_calls.append({"name": name, "arguments": args})
                if name == "tool_call":
                    underlying_tool_calls.append({
                        "name": str(args.get("name") or ""),
                        "arguments": args.get("arguments"),
                    })
    if msg.get("role") == "tool" and RUNTIME_SECRET in str(msg.get("content") or ""):
        tool_result_secret_seen = True

final_answer = str((convo or {}).get("final_response") or "").strip()
if not final_answer:
    for msg in reversed(messages):
        if msg.get("role") == "assistant" and str(msg.get("content") or "").strip():
            final_answer = str(msg.get("content") or "").strip()
            break

bridge_names = [row["name"] for row in bridge_calls]
terminal_via_bridge = any(row.get("name") == "terminal" for row in underlying_tool_calls)
exact_stub_call = any(str(row.get("command") or "").strip() == EXPECTED_COMMAND for row in terminal_calls)
secret_match = final_answer == RUNTIME_SECRET

result = {
    "model": model,
    "candidate": "defer-all-except-clarify",
    "raw_tool_count": len(raw_names),
    "deferred_count": len(raw_names - keep),
    "visible_tool_names": visible_names,
    "wall_s": wall_s,
    "api_turns": api_turns,
    "bridge_calls": bridge_calls,
    "bridge_call_names": bridge_names,
    "underlying_tool_calls": underlying_tool_calls,
    "terminal_stub_calls": terminal_calls,
    "terminal_via_bridge": terminal_via_bridge,
    "tool_result_secret_seen": tool_result_secret_seen,
    "exact_stub_call": exact_stub_call,
    "secret_match": secret_match,
    # Do not persist the secret itself; the equality check is sufficient evidence.
    "final_answer_length": len(final_answer),
}
print(json.dumps(result, ensure_ascii=False, indent=2))
RESULT_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

if not bridge_calls:
    raise SystemExit("FAIL: model made no progressive-disclosure bridge calls")
if "tool_call" not in bridge_names:
    raise SystemExit(f"FAIL: model never invoked tool_call; bridge calls={bridge_names}")
if not terminal_via_bridge:
    raise SystemExit(f"FAIL: terminal was not invoked through tool_call: {underlying_tool_calls}")
if not exact_stub_call:
    raise SystemExit(f"FAIL: safe terminal stub did not receive exact expected command: {terminal_calls}")
if not tool_result_secret_seen:
    raise SystemExit("FAIL: runtime secret was not observed in a tool result")
if not secret_match:
    raise SystemExit("FAIL: final answer did not exactly match the runtime-only secret")

print("PASS: Qwen invoked deferred terminal through progressive disclosure")
print("PASS: final answer exactly matched a runtime-only secret unavailable in the prompt")
print("PASS: no model-generated shell command was executed on the server (safe stub only)")
print(f"bridge path: {' -> '.join(bridge_names)}")
print(f"wall: {wall_s:.2f}s, API turns: {api_turns}")
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
        time.sleep(1)
        continue
    last = state
    platforms = state.get("platforms") or {}
    if (
        state.get("gateway_state") == "running"
        and (platforms.get("telegram") or {}).get("state") == "connected"
        and (platforms.get("api_server") or {}).get("state") == "connected"
    ):
        print("PASS: Hermes gateway running, Telegram connected, API connected")
        break
    time.sleep(1)
else:
    print(json.dumps(last, ensure_ascii=False, indent=2) if last else "<no readable gateway_state>")
    raise SystemExit("FAIL: Hermes did not fully reconnect within validation window")
PY
fi

"$HERMES_PYTHON" - <<'PY'
import json, urllib.request
with urllib.request.urlopen("http://127.0.0.1:11435/health", timeout=3) as r:
    h = json.load(r)
assert h.get("status") == "ok" and h.get("ollama") == "ok", h
with urllib.request.urlopen("http://127.0.0.1:11435/status", timeout=3) as r:
    s = json.load(r)
assert s.get("active_count") == 0 and s.get("queued_count") == 0, s
print("PASS: AI Gateway healthy and idle")
PY

say "analysis timer: $(systemctl is-active ai-bridge-analysis.timer 2>/dev/null || true)"
say "Hermes:         $(systemctl --user is-active hermes-gateway.service 2>/dev/null || true)"

trap - EXIT INT TERM
rm -rf "$TMP_ROOT"
section "DONE"
say "PASS: Stage-16B deferred-tool E2E validation completed"
say "No production Hermes config, database, routing, or toolset changes were made."
