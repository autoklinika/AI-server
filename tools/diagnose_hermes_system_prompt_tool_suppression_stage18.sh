#!/usr/bin/env bash
set -euo pipefail

HERMES_HOME="/srv/ai-data/hermes"
HERMES_SOURCE="${HERMES_HOME}/hermes-agent"
HERMES_PYTHON="${HERMES_SOURCE}/venv/bin/python"
HERMES_CONFIG="${HERMES_HOME}/config.yaml"
STATE_FILE="${HERMES_HOME}/gateway_state.json"
RESULT_JSON="/tmp/ai-gateway-stage18-system-prompt-tool-suppression.json"
TMP_ROOT="$(mktemp -d /tmp/ai-gateway-stage18.XXXXXX)"

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

section "STAGE-18 HERMES SYSTEM-PROMPT TOOL-SUPPRESSION DIAGNOSIS"
say "Read-only: no Hermes config/DB writes and no real tool execution."
say "Same model, user prompt and bridge tools; only system prompt changes."
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

section "BUILD INSTALLED AIAgent PROMPT + RUN A/B"
mkdir -p "$TMP_ROOT/hermes" "$TMP_ROOT/workspace"
cd "$HERMES_SOURCE"
HERMES_HOME="$TMP_ROOT/hermes" TERMINAL_CWD="$TMP_ROOT/workspace" \
"$HERMES_PYTHON" - "$HERMES_CONFIG" "$RESULT_JSON" <<'PY'
from pathlib import Path
import json, os, sys, time, urllib.request, yaml

PROD_CONFIG = Path(sys.argv[1])
RESULT_PATH = Path(sys.argv[2])
GATEWAY = "http://127.0.0.1:11435/clients/hermes/v1/chat/completions"

cfg = yaml.safe_load(PROD_CONFIG.read_text(encoding="utf-8")) or {}
model_cfg = cfg.get("model") or {}
model = str((model_cfg.get("default") or model_cfg.get("model")) if isinstance(model_cfg, dict) else model_cfg).strip()
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

# Isolated Hermes home.
Path(os.environ["HERMES_HOME"]).mkdir(parents=True, exist_ok=True)
Path(os.environ["HERMES_HOME"], "config.yaml").write_text(
    "model:\n  provider: custom\n  default: " + json.dumps(model) + "\n"
    "  base_url: http://127.0.0.1:11435/clients/hermes/v1\n"
    "agent:\n  reasoning_effort: none\n",
    encoding="utf-8",
)

import model_tools
import tools.tool_search as tool_search
from run_agent import AIAgent
from agent.system_prompt import build_system_prompt
from agent.prompt_builder import DEFAULT_AGENT_IDENTITY

# Build full Telegram raw surface and candidate defer-all-except-clarify.
model_tools._clear_tool_defs_cache()
raw_tools = model_tools.get_tool_definitions(enabled_toolsets=toolsets, quiet_mode=True, skip_tool_search_assembly=True)
raw_names = frozenset(
    str((t.get("function") or {}).get("name") or "")
    for t in raw_tools if (t.get("function") or {}).get("name")
)
keep = {"clarify"} & raw_names
candidate = tool_search.ToolSearchConfig(
    enabled="on", threshold_pct=5.0, search_default_limit=5, max_search_limit=25,
    listing="auto", listing_max_tokens=4000, defer_tools=frozenset(raw_names - keep),
)
orig_loader = tool_search.load_config
tool_search.load_config = lambda: candidate
model_tools._clear_tool_defs_cache()
try:
    agent = AIAgent(
        base_url="http://127.0.0.1:11435/clients/hermes/v1",
        api_key="stage18-local",
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
    full_system = build_system_prompt(agent)
    tools = list(getattr(agent, "tools", None) or [])
finally:
    tool_search.load_config = orig_loader
    model_tools._clear_tool_defs_cache()

names = [str((t.get("function") or {}).get("name") or "") for t in tools]
print("model-facing tools:", names)
required = {"tool_search", "tool_describe", "tool_call"}
if not required.issubset(set(names)):
    raise SystemExit(f"FAIL: missing bridge tools: {sorted(required-set(names))}")

user_prompt = (
    "A runtime-only secret is available only through the deferred terminal tool. "
    "You do not know the terminal schema yet. Begin by loading or discovering the terminal tool schema. "
    "Do not guess the secret and do not answer with prose before using a bridge tool."
)

variants = [
    ("minimal", "You are a tool-using assistant. Use the available tools when the task requires them."),
    ("identity-only", DEFAULT_AGENT_IDENTITY),
    ("full-aiagent", full_system),
    ("full-plus-explicit", full_system + "\n\nFor this diagnostic turn, a bridge tool call is mandatory before any prose response."),
]

def call(label, system):
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user_prompt},
        ],
        "tools": tools,
        "tool_choice": "auto",
        "reasoning_effort": "none",
        "temperature": 0,
        "max_tokens": 128,
        "stream": False,
    }
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(GATEWAY, data=data, method="POST", headers={"Content-Type":"application/json"})
    t0 = time.monotonic()
    with urllib.request.urlopen(req, timeout=900) as r:
        body = json.load(r)
    wall = time.monotonic() - t0
    choice = (body.get("choices") or [{}])[0]
    msg = choice.get("message") or {}
    tcalls = msg.get("tool_calls") or []
    call_names = [str((tc.get("function") or {}).get("name") or "") for tc in tcalls]
    row = {
        "label": label,
        "system_chars": len(system),
        "wall_s": wall,
        "finish_reason": choice.get("finish_reason"),
        "tool_call_names": call_names,
        "tool_call_count": len(call_names),
        "content_chars": len(str(msg.get("content") or "")),
        "reasoning_chars": len(str(msg.get("reasoning") or "")),
        "prompt_tokens": int((body.get("usage") or {}).get("prompt_tokens") or 0),
    }
    print("\n---", label, "---")
    print(json.dumps(row, ensure_ascii=False, indent=2))
    return row

rows = [call(label, system) for label, system in variants]
print("\n===== STAGE-18 DIAGNOSIS =====")
for row in rows:
    ok = bool(row["tool_call_count"])
    print(f"{row['label']:<19} {'TOOL_CALL' if ok else 'NO_TOOL'}  system={row['system_chars']:>6} chars  prompt={row['prompt_tokens']:>5} tok  wall={row['wall_s']:>6.2f}s  calls={row['tool_call_names']}")

minimal_ok = bool(rows[0]["tool_call_count"])
identity_ok = bool(rows[1]["tool_call_count"])
full_ok = bool(rows[2]["tool_call_count"])
explicit_ok = bool(rows[3]["tool_call_count"])
if minimal_ok and not full_ok:
    diagnosis = "FULL_HERMES_SYSTEM_PROMPT_SUPPRESSES_AUTO_TOOL_SELECTION"
elif minimal_ok and full_ok:
    diagnosis = "FULL_SYSTEM_PROMPT_NOT_SUFFICIENT_TO_REPRODUCE; investigate AIAgent conversation loop/request assembly"
elif not minimal_ok:
    diagnosis = "UNEXPECTED: bridge auto selection unstable even with minimal prompt"
else:
    diagnosis = "INCONCLUSIVE"
print("diagnosis:", diagnosis)
print("explicit full-system recovery:", "PASS" if explicit_ok else "FAIL")

RESULT_PATH.write_text(json.dumps({"model": model, "tool_names": names, "rows": rows, "diagnosis": diagnosis}, ensure_ascii=False, indent=2), encoding="utf-8")
print("full JSON:", RESULT_PATH)
PY

section "RESTORE + POSTCHECK"
if [ "$TIMER_WAS_ACTIVE" -eq 1 ]; then sudo systemctl start ai-bridge-analysis.timer; fi
if [ "$HERMES_WAS_ACTIVE" -eq 1 ]; then systemctl --user start hermes-gateway.service; fi

if [ "$HERMES_WAS_ACTIVE" -eq 1 ]; then
"$HERMES_PYTHON" - "$STATE_FILE" <<'PY'
from pathlib import Path
import json, sys, time
p = Path(sys.argv[1]); deadline=time.monotonic()+90; last=None
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
say "PASS: Stage-18 system-prompt diagnosis completed"
say "No production config, DB, or real tools were modified/executed."
