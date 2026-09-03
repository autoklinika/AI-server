#!/usr/bin/env bash
set -euo pipefail

HERMES_HOME="/srv/ai-data/hermes"
HERMES_CONFIG="${HERMES_HOME}/config.yaml"
HERMES_SOURCE="${HERMES_HOME}/hermes-agent"
HERMES_PYTHON="${HERMES_SOURCE}/venv/bin/python"
STATE_FILE="${HERMES_HOME}/gateway_state.json"
BACKUP="${HERMES_CONFIG}.pre-reasoning-none-stage9"
GATEWAY="http://127.0.0.1:11435"

say() { printf '%s\n' "$*"; }
section() { printf '\n===== %s =====\n' "$1"; }

[ -x "$HERMES_PYTHON" ] || { say "FAIL: Hermes Python missing: $HERMES_PYTHON"; exit 1; }
[ -r "$HERMES_CONFIG" ] || { say "FAIL: Hermes config missing: $HERMES_CONFIG"; exit 1; }
[ -d "$HERMES_SOURCE" ] || { say "FAIL: Hermes source missing: $HERMES_SOURCE"; exit 1; }
[ "$(systemctl --user is-active hermes-gateway.service 2>/dev/null || true)" = "active" ] || {
    say "FAIL: hermes-gateway.service is not active"
    exit 1
}
[ "$(systemctl is-active ai-gateway.service 2>/dev/null || true)" = "active" ] || {
    say "FAIL: ai-gateway.service is not active"
    exit 1
}

section "CONFIGURE HERMES REASONING OFF"
say "config: $HERMES_CONFIG"
say "rollback backup: $BACKUP"
say "Writes literal YAML string 'none' and validates the installed Hermes runtime."

section "PRECHECK"
"$HERMES_PYTHON" - "$HERMES_CONFIG" <<'PY'
from pathlib import Path
import sys, yaml
cfg = yaml.safe_load(Path(sys.argv[1]).read_text(encoding="utf-8")) or {}
value = (cfg.get("agent") or {}).get("reasoning_effort")
print("current raw value:", repr(value), "type:", type(value).__name__)
PY

"$HERMES_PYTHON" - <<'PY'
import json, urllib.request
with urllib.request.urlopen("http://127.0.0.1:11435/status", timeout=2) as r:
    s = json.load(r)
assert s.get("active_count") == 0 and s.get("queued_count") == 0, s
print("PASS: AI Gateway idle")
PY

section "BACKUP"
if [ ! -e "$BACKUP" ]; then
    cp --preserve=mode,timestamps "$HERMES_CONFIG" "$BACKUP"
    say "PASS: created rollback backup $BACKUP"
else
    [ -r "$BACKUP" ] || { say "FAIL: existing backup is not readable: $BACKUP"; exit 1; }
    say "INFO: rollback backup already exists; preserving it unchanged: $BACKUP"
fi

section "WRITE LITERAL STRING none"
"$HERMES_PYTHON" - "$HERMES_CONFIG" <<'PY'
from pathlib import Path
import os, sys, tempfile, yaml

path = Path(sys.argv[1])
cfg = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
if not isinstance(cfg, dict):
    raise SystemExit("FAIL: Hermes config root is not a mapping")
agent = cfg.get("agent")
if agent is None:
    agent = {}
    cfg["agent"] = agent
if not isinstance(agent, dict):
    raise SystemExit("FAIL: Hermes agent config is not a mapping")
agent["reasoning_effort"] = "none"

text = yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True, default_flow_style=False)
fd, tmp = tempfile.mkstemp(prefix="config.yaml.reasoning-none.", dir=str(path.parent), text=True)
try:
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    os.chmod(tmp, path.stat().st_mode & 0o777)
    os.replace(tmp, path)
finally:
    try:
        os.unlink(tmp)
    except FileNotFoundError:
        pass
print("PASS: wrote literal YAML string 'none' atomically")
PY

section "VALIDATE HERMES RUNTIME RESOLUTION"
"$HERMES_PYTHON" - "$HERMES_CONFIG" "$HERMES_SOURCE" <<'PY'
from pathlib import Path
import sys, yaml

config_path = Path(sys.argv[1])
source = sys.argv[2]
sys.path.insert(0, source)

cfg = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
value = (cfg.get("agent") or {}).get("reasoning_effort")
if value != "none" or not isinstance(value, str):
    raise SystemExit(f"FAIL: expected literal string 'none', got {value!r} ({type(value).__name__})")

from hermes_constants import resolve_reasoning_config
model_cfg = cfg.get("model") or {}
if isinstance(model_cfg, dict):
    model = str(model_cfg.get("default") or model_cfg.get("model") or "")
else:
    model = str(model_cfg)
resolved = resolve_reasoning_config(cfg, model)
print("raw agent.reasoning_effort:", repr(value))
print("Hermes resolve_reasoning_config:", repr(resolved))
if not isinstance(resolved, dict) or resolved.get("enabled") is not False:
    raise SystemExit(f"FAIL: Hermes runtime did not resolve reasoning disabled: {resolved!r}")

from providers import get_provider_profile
profile = get_provider_profile("custom")
if profile is None:
    raise SystemExit("FAIL: custom provider profile not found")
extra, top = profile.build_api_kwargs_extras(
    reasoning_config=resolved,
    base_url="http://127.0.0.1:11435/clients/hermes/v1",
)
print("custom provider top-level extras:", repr(top))
print("custom provider extra_body:", repr(extra))
if top.get("reasoning_effort") != "none":
    raise SystemExit(f"FAIL: custom provider did not emit reasoning_effort=none: {top!r}")
print("PASS: installed Hermes runtime resolves and emits reasoning_effort=none")
PY

section "RESTART HERMES"
systemctl --user restart hermes-gateway.service
for _ in $(seq 1 60); do
    if [ "$(systemctl --user is-active hermes-gateway.service 2>/dev/null || true)" = "active" ]; then
        break
    fi
    sleep 0.5
done
[ "$(systemctl --user is-active hermes-gateway.service 2>/dev/null || true)" = "active" ] || {
    say "FAIL: Hermes service did not return active"
    exit 1
}
say "PASS: Hermes service active"

section "WAIT FOR TELEGRAM + API CONNECTED"
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
    gateway = state.get("gateway_state")
    if gateway == "running" and telegram == "connected" and api == "connected":
        print("PASS: gateway running, Telegram connected, API connected")
        raise SystemExit(0)
    time.sleep(1)
print("FAIL: Hermes platforms did not reconnect within 90s")
print(json.dumps(last, ensure_ascii=False, indent=2) if last else "<no readable gateway_state>")
raise SystemExit(1)
PY

section "POSTCHECK"
"$HERMES_PYTHON" - <<'PY'
import json, urllib.request
with urllib.request.urlopen("http://127.0.0.1:11435/health", timeout=2) as r:
    h = json.load(r)
assert h.get("status") == "ok" and h.get("ollama") == "ok", h
with urllib.request.urlopen("http://127.0.0.1:11435/status", timeout=2) as r:
    s = json.load(r)
assert s.get("active_count") == 0 and s.get("queued_count") == 0, s
print("PASS: AI Gateway healthy and idle")
PY

say
echo "PASS: Hermes reasoning-off configuration completed"
say "Hermes runtime resolves literal agent.reasoning_effort='none' to enabled=False."
say "Rollback: tools/rollback_hermes_reasoning_none_stage9.sh"
