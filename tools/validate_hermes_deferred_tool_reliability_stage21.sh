#!/usr/bin/env bash
set -euo pipefail

PROD_HERMES_HOME="/srv/ai-data/hermes"
HERMES_SOURCE="${PROD_HERMES_HOME}/hermes-agent"
HERMES_PYTHON="${HERMES_SOURCE}/venv/bin/python"
HERMES_CONFIG="${PROD_HERMES_HOME}/config.yaml"
STATE_FILE="${PROD_HERMES_HOME}/gateway_state.json"
RESULT_JSON="/tmp/ai-gateway-stage21-deferred-tool-reliability.json"
TMP_ROOT="$(mktemp -d /tmp/ai-gateway-stage21.XXXXXX)"
TRIALS="${STAGE21_TRIALS:-5}"

say() { printf '%s\n' "$*"; }
section() { printf '\n===== %s =====\n' "$1"; }

[ -x "$HERMES_PYTHON" ] || { say "FAIL: Hermes Python missing: $HERMES_PYTHON"; exit 1; }
[ -r "$HERMES_CONFIG" ] || { say "FAIL: Hermes config missing: $HERMES_CONFIG"; exit 1; }
[ -d "$HERMES_SOURCE" ] || { say "FAIL: Hermes source missing: $HERMES_SOURCE"; exit 1; }
[ "$(systemctl is-active ai-gateway.service 2>/dev/null || true)" = "active" ] || { say "FAIL: ai-gateway.service is not active"; exit 1; }
[ "$(systemctl is-active ollama.service 2>/dev/null || true)" = "active" ] || { say "FAIL: ollama.service is not active"; exit 1; }
[[ "$TRIALS" =~ ^[1-9][0-9]*$ ]] || { say "FAIL: STAGE21_TRIALS must be a positive integer"; exit 1; }

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

section "STAGE-21 DEFERRED TOOL FULL-E2E RELIABILITY"
say "Candidate: full Telegram toolset + defer-all-except-clarify."
say "Runs ${TRIALS} fresh AIAgent trials with runtime-only secrets."
say "No production Hermes config/DB writes and no real shell execution."
say "Deferred terminal is replaced inside the isolated process by a safety stub."
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

section "RUN REPEATED ISOLATED FULL E2E"
mkdir -p "$TMP_ROOT/hermes" "$TMP_ROOT/workspace"
cd "$HERMES_SOURCE"
HERMES_HOME="$TMP_ROOT/hermes" TERMINAL_CWD="$TMP_ROOT/workspace" \
"$HERMES_PYTHON" - "$HERMES_CONFIG" "$RESULT_JSON" "$TRIALS" <<'PY'
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
TRIALS = int(sys.argv[3])
GATEWAY_BASE = "http://127.0.0.1:11435/clients/hermes/v1"
EXPECTED_COMMAND = "cat /tmp/stage21-runtime-secret"

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
from run_agent import AIAgent

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
stub_state = {"trial": 0, "secret": "", "calls": []}

def safe_terminal_stub(args, **kwargs):
    args = args if isinstance(args, dict) else {}
    command = str(args.get("command") or "").strip()
    stub_state["calls"].append({"trial": stub_state["trial"], "command": command})
    if command != EXPECTED_COMMAND:
        return json.dumps({
            "success": False,
            "error": "stage21 safety stub rejected unexpected command",
            "received_command": command,
            "expected_command": EXPECTED_COMMAND,
        })
    return json.dumps({"success": True, "stdout": stub_state["secret"] + "\n", "exit_code": 0})

terminal_entry.handler = safe_terminal_stub
terminal_entry.check_fn = None

prompt = (
    "This is an execution-verification task. The required value is unknown to you and exists only behind a local tool result. "
    "You MUST use the progressive-disclosure bridge to access the deferred terminal tool. "
    "Discover/describe the terminal tool as needed, then invoke it through tool_call with exactly this shell command: "
    + EXPECTED_COMMAND
    + ". Do not infer or invent the command output. After the tool returns, reply with ONLY the exact stdout value, with no quotes, label, or explanation. "
    "Do not use web, files, Python/code execution, clarify, or any other tool."
)

rows = []
try:
    for trial in range(1, TRIALS + 1):
        stub_state["trial"] = trial
        stub_state["secret"] = "S21_" + secrets.token_hex(12).upper()
        before_calls = len(stub_state["calls"])
        started = time.monotonic()
        agent = AIAgent(
            base_url=GATEWAY_BASE,
            api_key="stage21-local",
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
        convo = None
        error = None
        try:
            convo = agent.run_conversation(prompt)
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
        wall_s = time.monotonic() - started

        messages = (convo or {}).get("messages") or getattr(agent, "messages", []) or []
        bridge_names = []
        underlying = []
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
                        bridge_names.append(name)
                        if name == "tool_call":
                            underlying.append(str(args.get("name") or ""))
            if msg.get("role") == "tool" and stub_state["secret"] in str(msg.get("content") or ""):
                tool_result_secret_seen = True

        final_answer = str((convo or {}).get("final_response") or "").strip()
        if not final_answer:
            for msg in reversed(messages):
                if msg.get("role") == "assistant" and str(msg.get("content") or "").strip():
                    final_answer = str(msg.get("content") or "").strip()
                    break

        trial_stub_calls = stub_state["calls"][before_calls:]
        exact_stub = any(row.get("command") == EXPECTED_COMMAND for row in trial_stub_calls)
        terminal_via_bridge = "terminal" in underlying
        secret_match = final_answer == stub_state["secret"]
        passed = bool(
            not error
            and bridge_names
            and "tool_call" in bridge_names
            and terminal_via_bridge
            and exact_stub
            and tool_result_secret_seen
            and secret_match
        )
        row = {
            "trial": trial,
            "pass": passed,
            "wall_s": wall_s,
            "api_turns": api_turns,
            "visible_tool_names": visible_names,
            "bridge_path": bridge_names,
            "underlying_tool_names": underlying,
            "stub_call_count": len(trial_stub_calls),
            "terminal_via_bridge": terminal_via_bridge,
            "tool_result_secret_seen": tool_result_secret_seen,
            "secret_match": secret_match,
            "final_answer_length": len(final_answer),
            "error": error,
        }
        rows.append(row)
        print(json.dumps(row, ensure_ascii=False))
finally:
    terminal_entry.handler = original_terminal_handler
    terminal_entry.check_fn = original_terminal_check
    tool_search.load_config = original_load_config
    model_tools._clear_tool_defs_cache()

passes = sum(1 for row in rows if row["pass"])
summary = {
    "model": model,
    "candidate": "defer-all-except-clarify",
    "trials": TRIALS,
    "passes": passes,
    "failures": TRIALS - passes,
    "success_rate_pct": round(100.0 * passes / TRIALS, 1),
    "rows": rows,
}
RESULT_PATH.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
print("\n===== STAGE-21 RELIABILITY SUMMARY =====")
print(f"passes: {passes}/{TRIALS}")
print(f"success rate: {summary['success_rate_pct']:.1f}%")
for row in rows:
    print(
        f"trial {row['trial']}: {'PASS' if row['pass'] else 'FAIL'}  "
        f"wall={row['wall_s']:.2f}s  api_turns={row['api_turns']}  "
        f"bridge={' -> '.join(row['bridge_path']) or '<none>'}  "
        f"terminal={row['terminal_via_bridge']} secret={row['secret_match']}"
    )
print("full JSON:", RESULT_PATH)

if passes != TRIALS:
    raise SystemExit(f"FAIL: deferred-tool reliability was {passes}/{TRIALS}; production cutover is not approved")
print("PASS: all repeated full-E2E deferred-tool trials succeeded")
print("PASS: every final answer matched a runtime-only secret unavailable in the prompt")
print("PASS: no model-generated shell command was executed on the server (safe stub only)")
PY

section "RESTORE + POSTCHECK"
if [ "$TIMER_WAS_ACTIVE" -eq 1 ]; then sudo systemctl start ai-bridge-analysis.timer; fi
if [ "$HERMES_WAS_ACTIVE" -eq 1 ]; then systemctl --user start hermes-gateway.service; fi

if [ "$HERMES_WAS_ACTIVE" -eq 1 ]; then
    "$HERMES_PYTHON" - "$STATE_FILE" <<'PY'
from pathlib import Path
import json, sys, time
path = Path(sys.argv[1]); deadline = time.monotonic() + 90; last = None
while time.monotonic() < deadline:
    try:
        state = json.loads(path.read_text(encoding="utf-8")); last = state
    except Exception:
        time.sleep(1); continue
    p = state.get("platforms") or {}
    if state.get("gateway_state") == "running" and (p.get("telegram") or {}).get("state") == "connected" and (p.get("api_server") or {}).get("state") == "connected":
        print("PASS: Hermes gateway running, Telegram connected, API connected"); break
    time.sleep(1)
else:
    print(json.dumps(last, ensure_ascii=False, indent=2) if last else "<no state>")
    raise SystemExit("FAIL: Hermes did not reconnect")
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
say "PASS: Stage-21 repeated deferred-tool reliability validation completed"
say "No production Hermes config, DB, routing, or real tools were modified/executed."
