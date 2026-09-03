#!/usr/bin/env bash
set -euo pipefail

PROD_HERMES_HOME="/srv/ai-data/hermes"
HERMES_SOURCE="${PROD_HERMES_HOME}/hermes-agent"
HERMES_PYTHON="${HERMES_SOURCE}/venv/bin/python"
HERMES_CONFIG="${PROD_HERMES_HOME}/config.yaml"
STATE_FILE="${PROD_HERMES_HOME}/gateway_state.json"
RESULT_JSON="/tmp/ai-gateway-stage20-run-conversation-payload.json"
TMP_ROOT="$(mktemp -d /tmp/ai-gateway-stage20.XXXXXX)"

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

section "STAGE-20 RUN_CONVERSATION FIRST-PAYLOAD CAPTURE + EXACT REPLAY"
say "Read-only production diagnosis: isolated Hermes home, no production config/DB writes."
say "Deferred terminal is a safe stub; no model-generated shell command is executed."
say "Captures the first provider payload after run_conversation turn-context/middleware, then replays it unchanged."
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

section "CAPTURE FIRST REAL RUN_CONVERSATION REQUEST"
mkdir -p "$TMP_ROOT/hermes" "$TMP_ROOT/workspace"
cd "$HERMES_SOURCE"

HERMES_HOME="$TMP_ROOT/hermes" TERMINAL_CWD="$TMP_ROOT/workspace" \
"$HERMES_PYTHON" - "$HERMES_CONFIG" "$RESULT_JSON" <<'PY'
from __future__ import annotations

from pathlib import Path
import copy
import hashlib
import json
import os
import secrets
import sys
import time
import yaml

PROD_CONFIG = Path(sys.argv[1])
RESULT_PATH = Path(sys.argv[2])
GATEWAY_BASE = "http://127.0.0.1:11435/clients/hermes/v1"
EXPECTED_COMMAND = "cat /tmp/stage20-runtime-secret"
RUNTIME_SECRET = "S20_" + secrets.token_hex(12).upper()


def sha_text(value) -> str:
    if not isinstance(value, str):
        value = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()[:16]


def canonical_sha(value) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8", errors="replace")).hexdigest()[:16]


def summarize_response(resp):
    choices = list(getattr(resp, "choices", None) or [])
    choice = choices[0] if choices else None
    message = getattr(choice, "message", None) if choice is not None else None
    calls = list(getattr(message, "tool_calls", None) or []) if message is not None else []
    names = []
    for tc in calls:
        fn = getattr(tc, "function", None)
        names.append(str(getattr(fn, "name", "") or ""))
    content = getattr(message, "content", None) if message is not None else None
    usage = getattr(resp, "usage", None)
    return {
        "finish_reason": getattr(choice, "finish_reason", None) if choice is not None else None,
        "tool_call_names": names,
        "tool_call_count": len(names),
        "content_chars": len(str(content or "")),
        "prompt_tokens": int(getattr(usage, "prompt_tokens", 0) or 0) if usage is not None else 0,
        "completion_tokens": int(getattr(usage, "completion_tokens", 0) or 0) if usage is not None else 0,
    }


def payload_meta(payload):
    messages = list(payload.get("messages") or [])
    tools = list(payload.get("tools") or [])
    roles = [str(m.get("role") or "") for m in messages if isinstance(m, dict)]
    msg_meta = []
    for m in messages:
        if not isinstance(m, dict):
            continue
        content = m.get("content")
        msg_meta.append({
            "role": m.get("role"),
            "content_chars": len(content) if isinstance(content, str) else len(json.dumps(content, ensure_ascii=False, default=str)),
            "content_sha": sha_text(content),
            "keys": sorted(m.keys()),
        })
    tool_names = [str((t.get("function") or {}).get("name") or "") for t in tools if isinstance(t, dict)]
    return {
        "request_keys": sorted(payload.keys()),
        "serialized_bytes": len(json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")),
        "payload_sha": canonical_sha(payload),
        "message_count": len(messages),
        "message_roles": roles,
        "messages": msg_meta,
        "tools_count": len(tools),
        "tool_names": tool_names,
        "tools_sha": canonical_sha(tools),
        "temperature": payload.get("temperature"),
        "max_tokens": payload.get("max_tokens"),
        "reasoning_effort": payload.get("reasoning_effort"),
        "timeout": str(payload.get("timeout")) if "timeout" in payload else None,
        "extra_body_keys": sorted((payload.get("extra_body") or {}).keys()) if isinstance(payload.get("extra_body"), dict) else [],
    }

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
from agent.system_prompt import build_system_prompt

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
    raise SystemExit(f"FAIL: terminal missing from raw Telegram tools: {sorted(raw_names)}")

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
        return json.dumps({"success": False, "error": "stage20 safety stub rejected command"})
    return json.dumps({"success": True, "stdout": RUNTIME_SECRET + "\n", "exit_code": 0})

terminal_entry.handler = safe_terminal_stub
terminal_entry.check_fn = None

agent = AIAgent(
    base_url=GATEWAY_BASE,
    api_key="stage20-local",
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
required_visible = {"clarify", "tool_search", "tool_describe", "tool_call"}
if not required_visible.issubset(set(visible_names)):
    raise SystemExit(f"FAIL: candidate missing expected tools: {sorted(required_visible-set(visible_names))}")

prompt = (
    "This is an execution-verification task. The required value is unknown to you and exists only behind a local tool result. "
    "You MUST use the progressive-disclosure bridge to access the deferred terminal tool. "
    "Discover/describe the terminal tool as needed, then invoke it through tool_call with exactly this shell command: "
    + EXPECTED_COMMAND
    + ". Do not infer or invent the command output. After the tool returns, reply with ONLY the exact stdout value, with no quotes, label, or explanation. "
    "Do not use web, files, Python/code execution, clarify, or any other tool."
)

# Reference payload built before run_conversation turn-context/middleware.
reference_messages = [
    {"role": "system", "content": build_system_prompt(agent)},
    {"role": "user", "content": prompt},
]
reference_payload = agent._build_api_kwargs(reference_messages)
reference_meta = payload_meta(reference_payload)

captured_payload = None
first_loop_response = None
first_transport = None
original_stream = agent._interruptible_streaming_api_call
original_nonstream = agent._interruptible_api_call
provider_calls = 0

class StopBeforeSecondProviderCall(SystemExit):
    pass


def capture_and_call(kind, original, api_kwargs, **kwargs):
    global captured_payload, first_loop_response, first_transport, provider_calls
    provider_calls += 1
    if provider_calls > 1:
        raise StopBeforeSecondProviderCall()
    captured_payload = copy.deepcopy(api_kwargs)
    first_transport = kind
    response = original(api_kwargs, **kwargs)
    first_loop_response = summarize_response(response)
    return response


def wrapped_stream(api_kwargs, *, on_first_delta=None):
    return capture_and_call(
        "stream",
        original_stream,
        api_kwargs,
        on_first_delta=on_first_delta,
    )


def wrapped_nonstream(api_kwargs):
    return capture_and_call("nonstream", original_nonstream, api_kwargs)

agent._interruptible_streaming_api_call = wrapped_stream
agent._interruptible_api_call = wrapped_nonstream

run_error = None
run_final_length = 0
started = time.monotonic()
try:
    convo = agent.run_conversation(prompt)
    run_final = str((convo or {}).get("final_response") or "")
    run_final_length = len(run_final)
except StopBeforeSecondProviderCall:
    run_error = "STOPPED_BEFORE_SECOND_PROVIDER_CALL"
except BaseException as exc:
    run_error = f"{type(exc).__name__}: {exc}"
finally:
    run_wall_s = time.monotonic() - started
    agent._interruptible_streaming_api_call = original_stream
    agent._interruptible_api_call = original_nonstream

if captured_payload is None or first_loop_response is None:
    raise SystemExit(f"FAIL: did not capture first provider request/response; error={run_error}")

captured_meta = payload_meta(captured_payload)

# Exact same captured payload, same Hermes transport helper, repeated to expose
# model/tool-selection stability. No tool dispatch occurs during these replays.
replays = []
for idx in range(1, 5):
    t0 = time.monotonic()
    response = original_stream(copy.deepcopy(captured_payload))
    row = summarize_response(response)
    row["replay"] = idx
    row["wall_s"] = time.monotonic() - t0
    replays.append(row)

# One non-stream replay of the same payload for parity with Stage 19.
t0 = time.monotonic()
nonstream_response = original_nonstream(copy.deepcopy(captured_payload))
nonstream_replay = summarize_response(nonstream_response)
nonstream_replay["wall_s"] = time.monotonic() - t0

# Compare stable fields of pre-turn reference vs the actual first wire payload.
def compare_field(name):
    return {"reference": reference_meta.get(name), "captured": captured_meta.get(name), "equal": reference_meta.get(name) == captured_meta.get(name)}

comparison = {
    name: compare_field(name)
    for name in (
        "message_count", "message_roles", "tools_count", "tool_names", "tools_sha",
        "temperature", "max_tokens", "reasoning_effort", "extra_body_keys"
    )
}
comparison["system_sha_equal"] = (
    bool(reference_meta.get("messages")) and bool(captured_meta.get("messages"))
    and reference_meta["messages"][0].get("content_sha") == captured_meta["messages"][0].get("content_sha")
)
reference_user = next((m for m in reversed(reference_meta.get("messages") or []) if m.get("role") == "user"), None)
captured_user = next((m for m in reversed(captured_meta.get("messages") or []) if m.get("role") == "user"), None)
comparison["last_user_sha_equal"] = bool(reference_user and captured_user and reference_user.get("content_sha") == captured_user.get("content_sha"))

loop_has_bridge = bool(set(first_loop_response["tool_call_names"]) & {"tool_search", "tool_describe", "tool_call"})
stream_replay_bridge_count = sum(bool(set(r["tool_call_names"]) & {"tool_search", "tool_describe", "tool_call"}) for r in replays)
nonstream_has_bridge = bool(set(nonstream_replay["tool_call_names"]) & {"tool_search", "tool_describe", "tool_call"})

if loop_has_bridge:
    diagnosis = "RUN_CONVERSATION_FIRST_CALL_NOW_SELECTS_BRIDGE; prior Stage16B failure is not deterministic"
elif stream_replay_bridge_count == len(replays):
    diagnosis = "EXACT_SAME_PAYLOAD_FLIPS_FROM_PROSE_IN_LOOP_TO_TOOL_ON_REPLAY; model selection is nondeterministic/runtime-state-sensitive"
elif stream_replay_bridge_count > 0:
    diagnosis = "SAME_PAYLOAD_TOOL_SELECTION_IS_UNSTABLE_ACROSS_REPEATS"
elif not loop_has_bridge and stream_replay_bridge_count == 0 and not comparison["last_user_sha_equal"]:
    diagnosis = "RUN_CONVERSATION_MUTATES_USER_PAYLOAD; investigate turn-context user content"
elif not loop_has_bridge and stream_replay_bridge_count == 0:
    diagnosis = "CAPTURED_PAYLOAD_REPRODUCES_NO_TOOL; inspect payload differences vs reference"
else:
    diagnosis = "MIXED_RESULT"

result = {
    "model": model,
    "candidate": "defer-all-except-clarify",
    "visible_tool_names": visible_names,
    "first_transport": first_transport,
    "run_wall_s": run_wall_s,
    "run_error": run_error,
    "run_final_length": run_final_length,
    "first_loop_response": first_loop_response,
    "reference_payload_meta": reference_meta,
    "captured_payload_meta": captured_meta,
    "reference_vs_captured": comparison,
    "stream_replays": replays,
    "nonstream_replay": nonstream_replay,
    "loop_has_bridge": loop_has_bridge,
    "stream_replay_bridge_count": stream_replay_bridge_count,
    "nonstream_has_bridge": nonstream_has_bridge,
    "terminal_stub_call_count": len(terminal_calls),
    "diagnosis": diagnosis,
}

print("\n--- FIRST RESPONSE INSIDE run_conversation ---")
print(json.dumps(first_loop_response, ensure_ascii=False, indent=2))
print("first transport:", first_transport)
print("run error/status:", run_error)
print("run wall:", f"{run_wall_s:.2f}s")

print("\n--- ACTUAL FIRST PAYLOAD METADATA ---")
print(json.dumps(captured_meta, ensure_ascii=False, indent=2))

print("\n--- PRE-TURN REFERENCE vs ACTUAL CAPTURE ---")
print(json.dumps(comparison, ensure_ascii=False, indent=2))

print("\n--- EXACT CAPTURED PAYLOAD: STREAM REPLAYS ---")
for row in replays:
    print(json.dumps(row, ensure_ascii=False))
print("\n--- EXACT CAPTURED PAYLOAD: NON-STREAM REPLAY ---")
print(json.dumps(nonstream_replay, ensure_ascii=False, indent=2))

print("\n===== STAGE-20 DIAGNOSIS =====")
print("loop first bridge call:      ", "PASS" if loop_has_bridge else "FAIL")
print(f"exact stream replay bridge:  {stream_replay_bridge_count}/{len(replays)}")
print("exact non-stream bridge:     ", "PASS" if nonstream_has_bridge else "FAIL")
print("system SHA unchanged:        ", comparison["system_sha_equal"])
print("last user SHA unchanged:     ", comparison["last_user_sha_equal"])
print("temperature on wire:         ", repr(captured_meta.get("temperature")))
print("diagnosis:", diagnosis)

RESULT_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
print("full JSON:", RESULT_PATH)

terminal_entry.handler = original_terminal_handler
terminal_entry.check_fn = original_terminal_check
tool_search.load_config = original_load_config
model_tools._clear_tool_defs_cache()

print("PASS: Stage-20 captured the first run_conversation provider payload and replayed it exactly")
print("PASS: no model-generated shell command was executed on the server")
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
    platforms = state.get("platforms") or {}
    if state.get("gateway_state") == "running" and (platforms.get("telegram") or {}).get("state") == "connected" and (platforms.get("api_server") or {}).get("state") == "connected":
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
say "PASS: Stage-20 run_conversation payload capture/replay diagnosis completed"
say "No production Hermes config, DB, routing, or real tools were modified/executed."
