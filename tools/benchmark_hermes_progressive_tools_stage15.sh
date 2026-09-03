#!/usr/bin/env bash
set -euo pipefail

HERMES_HOME="/srv/ai-data/hermes"
HERMES_SOURCE="${HERMES_HOME}/hermes-agent"
HERMES_PYTHON="${HERMES_SOURCE}/venv/bin/python"
HERMES_CONFIG="${HERMES_HOME}/config.yaml"
STATE_FILE="${HERMES_HOME}/gateway_state.json"
RESULT_JSON="/tmp/ai-gateway-stage15-progressive-tools.json"

say() { printf '%s\n' "$*"; }
section() { printf '\n===== %s =====\n' "$1"; }

[ -x "$HERMES_PYTHON" ] || { say "FAIL: Hermes Python missing: $HERMES_PYTHON"; exit 1; }
[ -r "$HERMES_CONFIG" ] || { say "FAIL: Hermes config missing: $HERMES_CONFIG"; exit 1; }
[ -d "$HERMES_SOURCE" ] || { say "FAIL: Hermes source missing: $HERMES_SOURCE"; exit 1; }
[ "$(systemctl is-active ai-gateway.service 2>/dev/null || true)" = "active" ] || { say "FAIL: ai-gateway.service is not active"; exit 1; }
[ "$(systemctl is-active ollama.service 2>/dev/null || true)" = "active" ] || { say "FAIL: ollama.service is not active"; exit 1; }

export HERMES_HOME

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

section "STAGE-15 HERMES PROGRESSIVE TOOL DISCLOSURE BENCHMARK"
say "Temporary benchmark only: no configuration or database writes."
say "Tests the installed Hermes tool_search defer mechanism with the FULL Telegram toolset."
say "Hermes and ventilation analysis are paused only for inference isolation, then restored automatically."
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
print("model:", model_cfg.get("default") or model_cfg.get("model") if isinstance(model_cfg, dict) else model_cfg)
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

section "MEASURE PROGRESSIVE DISCLOSURE VARIANTS"
cd "$HERMES_SOURCE"
"$HERMES_PYTHON" - "$HERMES_CONFIG" "$RESULT_JSON" <<'PY'
from __future__ import annotations

from pathlib import Path
import json
import sys
import time
import urllib.request
import uuid
import yaml

CONFIG_PATH = Path(sys.argv[1])
RESULT_PATH = Path(sys.argv[2])
GATEWAY_URL = "http://127.0.0.1:11435/clients/hermes/v1/chat/completions"
STATUS_URL = "http://127.0.0.1:11435/status"

cfg = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}
model_cfg = cfg.get("model") or {}
if isinstance(model_cfg, dict):
    model = str(model_cfg.get("default") or model_cfg.get("model") or "").strip()
else:
    model = str(model_cfg).strip()
if not model:
    raise SystemExit("FAIL: could not resolve Hermes model")

from run_agent import AIAgent
from agent.system_prompt import build_system_prompt
from hermes_cli.tools_config import _get_platform_tools
import model_tools
import tools.tool_search as tool_search

current_toolsets = sorted(_get_platform_tools(cfg, "telegram"))
original_load_config = tool_search.load_config

# Resolve exactly the currently available raw Telegram surface before tool-search assembly.
model_tools._clear_tool_defs_cache()
raw_tools = model_tools.get_tool_definitions(
    enabled_toolsets=current_toolsets,
    quiet_mode=True,
    skip_tool_search_assembly=True,
)
raw_names = sorted(
    str((tool.get("function") or {}).get("name") or "")
    for tool in raw_tools
    if (tool.get("function") or {}).get("name")
)
raw_name_set = frozenset(raw_names)
print("raw available Telegram tools:", len(raw_names))
print("raw names:", ", ".join(raw_names))

ToolSearchConfig = tool_search.ToolSearchConfig

def ts_config(defer_names):
    return ToolSearchConfig(
        enabled="on",
        threshold_pct=5.0,
        search_default_limit=5,
        max_search_limit=25,
        listing="auto",
        listing_max_tokens=4000,
        defer_tools=frozenset(defer_names),
    )

# Maintainer guidance in Hermes keeps clarify eager because deferring it hurts
# structured clarification behavior. Web is another plausible eager working set.
keep_clarify = {"clarify"} & raw_name_set
keep_web_clarify = {"clarify", "web_search", "web_extract"} & raw_name_set

variants = [
    ("current-default", None),
    ("defer-all-except-web-clarify", ts_config(raw_name_set - keep_web_clarify)),
    ("defer-all-except-clarify", ts_config(raw_name_set - keep_clarify)),
    ("defer-all", ts_config(raw_name_set)),
]


def status():
    with urllib.request.urlopen(STATUS_URL, timeout=3) as r:
        return json.load(r)


def tool_names(tools):
    return [str((t.get("function") or {}).get("name") or "") for t in tools]


def build_agent(ts_cfg):
    # get_tool_definitions imports tools.tool_search.load_config at call time.
    # Monkeypatching this one loader lets us test a prospective config entirely
    # in-memory, while clearing the model-tools memo avoids cross-variant reuse.
    if ts_cfg is None:
        tool_search.load_config = original_load_config
    else:
        tool_search.load_config = lambda cfg=ts_cfg: cfg
    model_tools._clear_tool_defs_cache()
    return AIAgent(
        model=model,
        api_key="inspect-only",
        base_url="https://openrouter.ai/api/v1",
        provider="custom",
        api_mode="chat_completions",
        quiet_mode=True,
        save_trajectories=False,
        platform="telegram",
        enabled_toolsets=current_toolsets,
        reasoning_config={"enabled": False},
    )


def assembly_meta(ts_cfg):
    cfg_obj = original_load_config() if ts_cfg is None else ts_cfg
    result = tool_search.assemble_tool_defs(raw_tools, context_length=65536, config=cfg_obj)
    return {
        "activated": bool(result.activated),
        "deferred_count": int(result.deferred_count),
        "tier": int(getattr(result, "tier", 0) or 0),
        "listing_form": str(getattr(result, "listing_form", "none") or "none"),
        "visible_names": tool_names(result.tool_defs),
    }


def run_variant(label, ts_cfg):
    s = status()
    if s.get("active_count") or s.get("queued_count"):
        raise SystemExit(f"FAIL: gateway not idle before {label}: {s}")

    meta = assembly_meta(ts_cfg)
    agent = build_agent(ts_cfg)
    system_prompt = build_system_prompt(agent)
    tools = list(getattr(agent, "tools", None) or [])
    names = tool_names(tools)
    tools_json = json.dumps(tools, ensure_ascii=False, separators=(",", ":"))

    nonce = uuid.uuid4().hex
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": f"[stage15:{nonce}]\n{system_prompt}"},
            {"role": "user", "content": "Napisz dokładnie: STAGE15_OK. Nie używaj narzędzi."},
        ],
        "tools": tools,
        "tool_choice": "none",
        "reasoning_effort": "none",
        "temperature": 0,
        "max_tokens": 32,
        "stream": False,
    }
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(GATEWAY_URL, data=data, method="POST", headers={"Content-Type": "application/json"})
    started = time.monotonic()
    with urllib.request.urlopen(req, timeout=900) as response:
        body = json.load(response)
        elapsed = time.monotonic() - started

    usage = body.get("usage") or {}
    choice = ((body.get("choices") or [{}])[0])
    message = choice.get("message") or {}
    row = {
        "label": label,
        "raw_tool_count": len(raw_tools),
        "visible_tool_count": len(tools),
        "visible_tool_names": names,
        "assembly": meta,
        "system_prompt_chars": len(system_prompt),
        "tool_schema_chars": len(tools_json),
        "wire_payload_bytes": len(data),
        "wall_s": elapsed,
        "prompt_tokens": int(usage.get("prompt_tokens") or 0),
        "completion_tokens": int(usage.get("completion_tokens") or 0),
        "content_chars": len(str(message.get("content") or "")),
        "reasoning_chars": len(str(message.get("reasoning") or "")),
        "finish_reason": choice.get("finish_reason"),
    }
    print(json.dumps(row, ensure_ascii=False, indent=2))
    return row

results = []
try:
    for label, ts_cfg in variants:
        print(f"\n--- {label} ---")
        results.append(run_variant(label, ts_cfg))
finally:
    tool_search.load_config = original_load_config
    model_tools._clear_tool_defs_cache()

base = results[0]
print("\n===== STAGE-15 COMPARISON =====")
for row in results:
    tok_red = (1.0 - row["prompt_tokens"] / base["prompt_tokens"]) * 100.0 if base["prompt_tokens"] else 0.0
    wall_red = (1.0 - row["wall_s"] / base["wall_s"]) * 100.0 if base["wall_s"] else 0.0
    a = row["assembly"]
    print(
        f"{row['label']:<31} prompt={row['prompt_tokens']:>6} tok  wall={row['wall_s']:>7.2f}s  "
        f"visible={row['visible_tool_count']:>2}/{row['raw_tool_count']:<2} deferred={a['deferred_count']:>2}  "
        f"tier={a['tier']} listing={a['listing_form']:<5}  token_reduction={tok_red:>5.1f}%  wall_reduction={wall_red:>5.1f}%"
    )

print("\n===== DISCOVERABILITY CHECK =====")
for row in results[1:]:
    visible = set(row["visible_tool_names"])
    bridges = {"tool_search", "tool_describe", "tool_call"}
    missing = sorted(bridges - visible)
    if missing:
        raise SystemExit(f"FAIL: {row['label']} missing bridge tools: {missing}")
    print(f"PASS: {row['label']} exposes all three tool-search bridge tools; listing={row['assembly']['listing_form']}")

RESULT_PATH.write_text(json.dumps({"model": model, "raw_tool_names": raw_names, "results": results}, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"\nfull JSON: {RESULT_PATH}")
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
section "DONE"
say "PASS: Stage-15 progressive tool-disclosure benchmark completed"
say "No Hermes config, database, routing, or toolset changes were made."
