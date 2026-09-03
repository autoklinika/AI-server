#!/usr/bin/env bash
set -euo pipefail

PROD_HERMES_HOME="/srv/ai-data/hermes"
HERMES_SOURCE="${PROD_HERMES_HOME}/hermes-agent"
HERMES_PYTHON="${HERMES_SOURCE}/venv/bin/python"
HERMES_CONFIG="${PROD_HERMES_HOME}/config.yaml"
STATE_FILE="${PROD_HERMES_HOME}/gateway_state.json"
RESULT_JSON="/tmp/ai-gateway-stage19-streaming-tool-calls.json"
TMP_ROOT="$(mktemp -d /tmp/ai-gateway-stage19.XXXXXX)"

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

section "STAGE-19 HERMES STREAMING TOOL-CALL DIAGNOSIS"
say "Read-only: no production config/DB writes and no real tool execution."
say "Same AIAgent-built request; compare non-stream vs stream and SDK vs Hermes helper."
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

section "BUILD IDENTICAL AIAgent REQUEST + RUN STREAM MATRIX"
mkdir -p "$TMP_ROOT/hermes" "$TMP_ROOT/workspace"
cd "$HERMES_SOURCE"
HERMES_HOME="$TMP_ROOT/hermes" TERMINAL_CWD="$TMP_ROOT/workspace" \
"$HERMES_PYTHON" - "$HERMES_CONFIG" "$RESULT_JSON" <<'PY'
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import copy
import json
import os
import sys
import time
import yaml

PROD_CONFIG = Path(sys.argv[1])
RESULT_PATH = Path(sys.argv[2])
BASE_URL = "http://127.0.0.1:11435/clients/hermes/v1"

cfg = yaml.safe_load(PROD_CONFIG.read_text(encoding="utf-8")) or {}
model_cfg = cfg.get("model") or {}
if isinstance(model_cfg, dict):
    model = str(model_cfg.get("default") or model_cfg.get("model") or "").strip()
else:
    model = str(model_cfg).strip()
if not model:
    raise SystemExit("FAIL: could not resolve model")

platform_toolsets = cfg.get("platform_toolsets") or {}
configured = platform_toolsets.get("telegram") if isinstance(platform_toolsets, dict) else None
if isinstance(configured, str):
    toolsets = [configured]
elif isinstance(configured, list) and configured:
    toolsets = [str(x) for x in configured if str(x).strip()]
else:
    toolsets = ["hermes-telegram"]

Path(os.environ["HERMES_HOME"]).mkdir(parents=True, exist_ok=True)
Path(os.environ["HERMES_HOME"], "config.yaml").write_text(
    "model:\n  provider: custom\n  default: " + json.dumps(model) + "\n"
    "  base_url: " + json.dumps(BASE_URL) + "\n"
    "agent:\n  reasoning_effort: none\n",
    encoding="utf-8",
)

import model_tools
import tools.tool_search as tool_search
from run_agent import AIAgent
from agent.system_prompt import build_system_prompt

model_tools._clear_tool_defs_cache()
raw_tools = model_tools.get_tool_definitions(
    enabled_toolsets=toolsets,
    quiet_mode=True,
    skip_tool_search_assembly=True,
)
raw_names = frozenset(
    str((t.get("function") or {}).get("name") or "")
    for t in raw_tools
    if (t.get("function") or {}).get("name")
)
keep = {"clarify"} & raw_names
candidate = tool_search.ToolSearchConfig(
    enabled="on",
    threshold_pct=5.0,
    search_default_limit=5,
    max_search_limit=25,
    listing="auto",
    listing_max_tokens=4000,
    defer_tools=frozenset(raw_names - keep),
)
orig_loader = tool_search.load_config
tool_search.load_config = lambda: candidate
model_tools._clear_tool_defs_cache()
try:
    agent = AIAgent(
        base_url=BASE_URL,
        api_key="stage19-local",
        provider="custom",
        api_mode="chat_completions",
        model=model,
        quiet_mode=True,
        platform="telegram",
        enabled_toolsets=toolsets,
        reasoning_config={"enabled": False},
        max_tokens=128,
        save_trajectories=False,
        skip_context_files=True,
        skip_memory=True,
        skip_background_review=True,
    )
    system_prompt = build_system_prompt(agent)
    tool_names = [
        str((t.get("function") or {}).get("name") or "")
        for t in (getattr(agent, "tools", None) or [])
    ]
finally:
    tool_search.load_config = orig_loader
    model_tools._clear_tool_defs_cache()

required = {"tool_search", "tool_describe", "tool_call"}
if not required.issubset(set(tool_names)):
    raise SystemExit(f"FAIL: missing bridge tools: {sorted(required-set(tool_names))}")
print("model-facing tools:", tool_names)

user_prompt = (
    "A runtime-only secret is available only through the deferred terminal tool. "
    "You do not know the terminal schema yet. Begin by loading or discovering the terminal tool schema. "
    "Do not guess the secret and do not answer with prose before using a bridge tool."
)
messages = [
    {"role": "system", "content": system_prompt},
    {"role": "user", "content": user_prompt},
]
api_kwargs = agent._build_api_kwargs(messages)
api_kwargs["temperature"] = 0
api_kwargs["max_tokens"] = 128
# The OpenAI SDK treats stream as an invocation option; keep the shared base request stream-neutral.
api_kwargs.pop("stream", None)
api_kwargs.pop("stream_options", None)

print("AIAgent request keys:", sorted(api_kwargs.keys()))
print("AIAgent messages:", len(api_kwargs.get("messages") or []))
print("AIAgent tools:", len(api_kwargs.get("tools") or []))
print("AIAgent reasoning_effort:", repr(api_kwargs.get("reasoning_effort")))


def ns_tool_names(response):
    choices = getattr(response, "choices", None) or []
    if not choices:
        return [], None, 0
    choice = choices[0]
    message = getattr(choice, "message", None)
    calls = getattr(message, "tool_calls", None) or [] if message is not None else []
    names = []
    for tc in calls:
        fn = getattr(tc, "function", None)
        names.append(str(getattr(fn, "name", "") or ""))
    content = str(getattr(message, "content", "") or "") if message is not None else ""
    return names, getattr(choice, "finish_reason", None), len(content)


def run_sdk_nonstream():
    t0 = time.monotonic()
    response = agent.client.chat.completions.create(**copy.deepcopy(api_kwargs), stream=False)
    wall = time.monotonic() - t0
    names, finish, content_chars = ns_tool_names(response)
    return {
        "label": "sdk-nonstream",
        "wall_s": wall,
        "finish_reason": finish,
        "tool_call_names": names,
        "tool_call_count": len(names),
        "content_chars": content_chars,
    }


def run_sdk_stream_manual():
    kwargs = copy.deepcopy(api_kwargs)
    kwargs["stream"] = True
    kwargs["stream_options"] = {"include_usage": True}
    t0 = time.monotonic()
    stream = agent.client.chat.completions.create(**kwargs)
    tool_acc = {}
    finish = None
    content_chars = 0
    chunk_count = 0
    for chunk in stream:
        chunk_count += 1
        choices = getattr(chunk, "choices", None) or []
        if not choices:
            continue
        choice = choices[0]
        if getattr(choice, "finish_reason", None) is not None:
            finish = getattr(choice, "finish_reason", None)
        delta = getattr(choice, "delta", None)
        if delta is None:
            continue
        content = getattr(delta, "content", None)
        if content:
            content_chars += len(str(content))
        for tc in (getattr(delta, "tool_calls", None) or []):
            idx = int(getattr(tc, "index", 0) or 0)
            entry = tool_acc.setdefault(idx, {"name": "", "arguments": ""})
            fn = getattr(tc, "function", None)
            if fn is not None:
                name_part = getattr(fn, "name", None)
                args_part = getattr(fn, "arguments", None)
                if name_part:
                    entry["name"] += str(name_part)
                if args_part:
                    entry["arguments"] += str(args_part)
    wall = time.monotonic() - t0
    names = [tool_acc[i]["name"] for i in sorted(tool_acc) if tool_acc[i]["name"]]
    return {
        "label": "sdk-stream-manual",
        "wall_s": wall,
        "finish_reason": finish,
        "tool_call_names": names,
        "tool_call_count": len(names),
        "content_chars": content_chars,
        "chunk_count": chunk_count,
    }


def run_hermes_nonstream_helper():
    t0 = time.monotonic()
    response = agent._interruptible_api_call(copy.deepcopy(api_kwargs))
    wall = time.monotonic() - t0
    names, finish, content_chars = ns_tool_names(response)
    return {
        "label": "hermes-nonstream-helper",
        "wall_s": wall,
        "finish_reason": finish,
        "tool_call_names": names,
        "tool_call_count": len(names),
        "content_chars": content_chars,
    }


def run_hermes_stream_helper():
    t0 = time.monotonic()
    response = agent._interruptible_streaming_api_call(copy.deepcopy(api_kwargs))
    wall = time.monotonic() - t0
    names, finish, content_chars = ns_tool_names(response)
    return {
        "label": "hermes-stream-helper",
        "wall_s": wall,
        "finish_reason": finish,
        "tool_call_names": names,
        "tool_call_count": len(names),
        "content_chars": content_chars,
    }

rows = []
for fn in (run_sdk_nonstream, run_sdk_stream_manual, run_hermes_nonstream_helper, run_hermes_stream_helper):
    print("\n---", fn.__name__, "---")
    try:
        row = fn()
    except Exception as exc:
        row = {
            "label": fn.__name__,
            "error": f"{type(exc).__name__}: {exc}",
            "tool_call_names": [],
            "tool_call_count": 0,
        }
    rows.append(row)
    print(json.dumps(row, ensure_ascii=False, indent=2))

by = {row["label"]: row for row in rows}
bridge = {"tool_search", "tool_describe", "tool_call"}

def ok(label):
    return bool(bridge & set(by.get(label, {}).get("tool_call_names") or []))

sdk_ns = ok("sdk-nonstream")
sdk_stream = ok("sdk-stream-manual")
hermes_ns = ok("hermes-nonstream-helper")
hermes_stream = ok("hermes-stream-helper")

print("\n===== STAGE-19 DIAGNOSIS =====")
print("SDK non-stream:         ", "PASS" if sdk_ns else "FAIL")
print("SDK stream/manual parse:", "PASS" if sdk_stream else "FAIL")
print("Hermes non-stream:      ", "PASS" if hermes_ns else "FAIL")
print("Hermes stream helper:   ", "PASS" if hermes_stream else "FAIL")

if sdk_ns and not sdk_stream:
    diagnosis = "OLLAMA_OPENAI_STREAMING_TOOL_CALL_PATH_FAILS"
elif sdk_stream and not hermes_stream:
    diagnosis = "HERMES_STREAM_ASSEMBLER_DROPS_TOOL_CALLS"
elif sdk_ns and sdk_stream and hermes_ns and hermes_stream:
    diagnosis = "STREAMING_PATH_WORKS; investigate run_conversation turn-context/request mutation"
elif not sdk_ns:
    diagnosis = "CONTROL_UNSTABLE; non-stream request did not select bridge tool"
else:
    diagnosis = "MIXED_RESULT; inspect rows"
print("diagnosis:", diagnosis)

RESULT_PATH.write_text(json.dumps({
    "model": model,
    "tool_names": tool_names,
    "request_keys": sorted(api_kwargs.keys()),
    "rows": rows,
    "diagnosis": diagnosis,
}, ensure_ascii=False, indent=2), encoding="utf-8")
print("full JSON:", RESULT_PATH)
PY

section "RESTORE + POSTCHECK"
if [ "$TIMER_WAS_ACTIVE" -eq 1 ]; then sudo systemctl start ai-bridge-analysis.timer; fi
if [ "$HERMES_WAS_ACTIVE" -eq 1 ]; then systemctl --user start hermes-gateway.service; fi

if [ "$HERMES_WAS_ACTIVE" -eq 1 ]; then
"$HERMES_PYTHON" - "$STATE_FILE" <<'PY'
from pathlib import Path
import json, sys, time
p=Path(sys.argv[1]); deadline=time.monotonic()+90; last=None
while time.monotonic()<deadline:
    try: s=json.loads(p.read_text(encoding="utf-8")); last=s
    except Exception: time.sleep(1); continue
    platforms=s.get("platforms") or {}
    if s.get("gateway_state")=="running" and (platforms.get("telegram") or {}).get("state")=="connected" and (platforms.get("api_server") or {}).get("state")=="connected":
        print("PASS: Hermes gateway running, Telegram connected, API connected"); break
    time.sleep(1)
else:
    print(json.dumps(last, ensure_ascii=False, indent=2) if last else "<no state>")
    raise SystemExit("FAIL: Hermes did not reconnect")
PY
fi

"$HERMES_PYTHON" - <<'PY'
import json, urllib.request
with urllib.request.urlopen("http://127.0.0.1:11435/health", timeout=3) as r: h=json.load(r)
assert h.get("status")=="ok" and h.get("ollama")=="ok", h
with urllib.request.urlopen("http://127.0.0.1:11435/status", timeout=3) as r: s=json.load(r)
assert s.get("active_count")==0 and s.get("queued_count")==0, s
print("PASS: AI Gateway healthy and idle")
PY
say "analysis timer: $(systemctl is-active ai-bridge-analysis.timer 2>/dev/null || true)"
say "Hermes:         $(systemctl --user is-active hermes-gateway.service 2>/dev/null || true)"

trap - EXIT INT TERM
rm -rf "$TMP_ROOT"
section "DONE"
say "PASS: Stage-19 streaming tool-call diagnosis completed"
say "No production config, DB, or real tools were modified/executed."
