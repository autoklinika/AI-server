#!/usr/bin/env bash
set -euo pipefail

HERMES_HOME="/srv/ai-data/hermes"
HERMES_SOURCE="${HERMES_HOME}/hermes-agent"
HERMES_PYTHON="${HERMES_SOURCE}/venv/bin/python"
HERMES_CONFIG="${HERMES_HOME}/config.yaml"
STATE_FILE="${HERMES_HOME}/gateway_state.json"
GATEWAY="http://127.0.0.1:11435"
RESULT_JSON="/tmp/ai-gateway-stage13-toolset-benchmark.json"

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
    if [ "$TIMER_WAS_ACTIVE" -eq 1 ]; then
        sudo systemctl start ai-bridge-analysis.timer >/dev/null 2>&1 || true
    fi
    if [ "$HERMES_WAS_ACTIVE" -eq 1 ]; then
        systemctl --user start hermes-gateway.service >/dev/null 2>&1 || true
    fi
    exit "$rc"
}
trap restore EXIT INT TERM

section "STAGE-13 HERMES TOOLSET LATENCY BENCHMARK"
say "Temporary benchmark only: no configuration or database writes."
say "Live Hermes and ventilation analysis are paused only for measurement isolation, then restored automatically."
say "model/config source: $HERMES_CONFIG"
say "result JSON: $RESULT_JSON"

section "PRECHECK"
"$HERMES_PYTHON" - "$HERMES_CONFIG" <<'PY'
from pathlib import Path
import sys, yaml
cfg = yaml.safe_load(Path(sys.argv[1]).read_text(encoding="utf-8")) or {}
agent = cfg.get("agent") or {}
value = agent.get("reasoning_effort")
print("agent.reasoning_effort:", repr(value))
if value != "none":
    raise SystemExit("FAIL: expected literal agent.reasoning_effort='none'")
model_cfg = cfg.get("model") or {}
if isinstance(model_cfg, dict):
    print("model:", model_cfg.get("default") or model_cfg.get("model"))
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

section "BUILD REAL HERMES PROMPTS + RUN CONTROLLED REQUESTS"
cd "$HERMES_SOURCE"
"$HERMES_PYTHON" - "$HERMES_CONFIG" "$RESULT_JSON" <<'PY'
from __future__ import annotations

from pathlib import Path
import json
import os
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

current = sorted(_get_platform_tools(cfg, "telegram"))
variants = [
    ("current-telegram", current),
    ("core-plus-web", ["terminal", "file", "web", "skills", "todo"]),
    ("no-tools", []),
]


def status() -> dict:
    with urllib.request.urlopen(STATUS_URL, timeout=3) as r:
        return json.load(r)


def build_agent(toolsets: list[str]):
    # Mirrors Hermes' own prompt-size diagnostic: direct construction with
    # dummy credentials builds the real prompt/tool surface without a network call.
    return AIAgent(
        model=model,
        api_key="inspect-only",
        base_url="https://openrouter.ai/api/v1",
        provider="custom",
        api_mode="chat_completions",
        quiet_mode=True,
        save_trajectories=False,
        platform="telegram",
        enabled_toolsets=toolsets,
        reasoning_config={"enabled": False},
    )


def run_variant(label: str, toolsets: list[str]) -> dict:
    s = status()
    if s.get("active_count") or s.get("queued_count"):
        raise SystemExit(f"FAIL: gateway not idle before {label}: {s}")

    agent = build_agent(toolsets)
    system_prompt = build_system_prompt(agent)
    tools = list(getattr(agent, "tools", None) or [])
    tools_json = json.dumps(tools, ensure_ascii=False, separators=(",", ":"))

    # Unique prefix defeats cross-request prefix/KV reuse, so each variant pays
    # its own prompt-evaluation cost instead of inheriting a cached common prefix.
    nonce = uuid.uuid4().hex
    system_wire = f"[stage13:{nonce}]\n{system_prompt}"
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_wire},
            {"role": "user", "content": "Napisz dokładnie: STAGE13_OK. Nie używaj narzędzi."},
        ],
        "tools": tools,
        "tool_choice": "none",
        "reasoning_effort": "none",
        "temperature": 0,
        "max_tokens": 32,
        "stream": False,
    }
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        GATEWAY_URL,
        data=data,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    started = time.monotonic()
    with urllib.request.urlopen(req, timeout=900) as response:
        body = json.load(response)
        elapsed = time.monotonic() - started
        headers = dict(response.headers.items())

    usage = body.get("usage") or {}
    choices = body.get("choices") or []
    choice = choices[0] if choices else {}
    message = choice.get("message") or {}
    result = {
        "label": label,
        "toolsets": toolsets,
        "system_prompt_chars": len(system_prompt),
        "system_prompt_bytes": len(system_prompt.encode("utf-8")),
        "tool_count": len(tools),
        "tool_schema_chars": len(tools_json),
        "wire_payload_bytes": len(data),
        "wall_s": elapsed,
        "prompt_tokens": int(usage.get("prompt_tokens") or 0),
        "completion_tokens": int(usage.get("completion_tokens") or 0),
        "total_tokens": int(usage.get("total_tokens") or 0),
        "content_chars": len(str(message.get("content") or "")),
        "reasoning_chars": len(str(message.get("reasoning") or "")),
        "finish_reason": choice.get("finish_reason"),
        "gateway_job_id": headers.get("X-AI-Gateway-Job-Id"),
        "gateway_wait_ms": headers.get("X-AI-Gateway-Wait-Ms"),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


results = []
for label, toolsets in variants:
    print(f"\n--- {label} ---")
    results.append(run_variant(label, toolsets))

base = results[0]
print("\n===== STAGE-13 COMPARISON =====")
for row in results:
    token_reduction = 0.0
    wall_reduction = 0.0
    if base["prompt_tokens"]:
        token_reduction = (1.0 - row["prompt_tokens"] / base["prompt_tokens"]) * 100.0
    if base["wall_s"]:
        wall_reduction = (1.0 - row["wall_s"] / base["wall_s"]) * 100.0
    print(
        f"{row['label']:<18} prompt={row['prompt_tokens']:>6} tok  "
        f"wall={row['wall_s']:>7.2f}s  tools={row['tool_count']:>2}  "
        f"schema={row['tool_schema_chars']:>6} chars  "
        f"token_reduction={token_reduction:>6.1f}%  wall_reduction={wall_reduction:>6.1f}%"
    )

RESULT_PATH.write_text(json.dumps({"model": model, "results": results}, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"\nfull JSON: {RESULT_PATH}")
PY

section "POSTCHECK BEFORE RESTORE"
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

# Explicit restore here lets us validate it; EXIT trap remains a safety net.
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
    telegram = (platforms.get("telegram") or {}).get("state")
    api = (platforms.get("api_server") or {}).get("state")
    if state.get("gateway_state") == "running" and telegram == "connected" and api == "connected":
        print("PASS: Hermes gateway running, Telegram connected, API connected")
        raise SystemExit(0)
    time.sleep(1)
print("FAIL: Hermes did not fully reconnect within validation window")
print(json.dumps(last, ensure_ascii=False, indent=2) if last else "<no readable gateway_state>")
raise SystemExit(1)
PY
fi

say "analysis timer: $(systemctl is-active ai-bridge-analysis.timer 2>/dev/null || true)"
say "Hermes:         $(systemctl --user is-active hermes-gateway.service 2>/dev/null || true)"

trap - EXIT INT TERM
section "DONE"
say "PASS: Stage-13 controlled Hermes toolset latency benchmark completed"
say "No permanent Hermes toolset or routing changes were made."
