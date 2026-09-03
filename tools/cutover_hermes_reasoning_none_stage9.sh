#!/usr/bin/env bash
set -euo pipefail

HERMES_HOME="/srv/ai-data/hermes"
HERMES_CONFIG="${HERMES_HOME}/config.yaml"
HERMES_BIN="${HOME}/.local/bin/hermes"
HERMES_PYTHON="${HERMES_HOME}/hermes-agent/venv/bin/python"
BACKUP="${HERMES_CONFIG}.pre-reasoning-none-stage9"
GATEWAY="http://127.0.0.1:11435"

say() { printf '%s\n' "$*"; }
section() { printf '\n===== %s =====\n' "$1"; }

[ -x "$HERMES_BIN" ] || { say "FAIL: Hermes CLI missing: $HERMES_BIN"; exit 1; }
[ -x "$HERMES_PYTHON" ] || { say "FAIL: Hermes Python missing: $HERMES_PYTHON"; exit 1; }
[ -r "$HERMES_CONFIG" ] || { say "FAIL: Hermes config missing: $HERMES_CONFIG"; exit 1; }
[ "$(systemctl --user is-active hermes-gateway.service 2>/dev/null || true)" = "active" ] || {
    say "FAIL: hermes-gateway.service is not active"
    exit 1
}
[ "$(systemctl is-active ai-gateway.service 2>/dev/null || true)" = "active" ] || {
    say "FAIL: ai-gateway.service is not active"
    exit 1
}

section "STAGE-9 HERMES REASONING-OFF CUTOVER"
say "config: $HERMES_CONFIG"
say "backup: $BACKUP"
say "Hermes service: $(systemctl --user is-active hermes-gateway.service)"
say "AI Gateway:     $(systemctl is-active ai-gateway.service)"

section "PRECHECK"
"$HERMES_PYTHON" - "$HERMES_CONFIG" <<'PY'
from pathlib import Path
import sys, yaml
cfg = yaml.safe_load(Path(sys.argv[1]).read_text(encoding="utf-8")) or {}
agent = cfg.get("agent") or {}
print("current agent.reasoning_effort:", repr(agent.get("reasoning_effort")))
model = cfg.get("model") or {}
if isinstance(model, dict):
    print("model:", model.get("default") or model.get("model"))
else:
    print("model:", model)
PY

"$HERMES_PYTHON" - <<'PY'
import json, urllib.request
with urllib.request.urlopen("http://127.0.0.1:11435/status", timeout=2) as r:
    s = json.load(r)
assert s.get("active_count") == 0 and s.get("queued_count") == 0, s
print("PASS: AI Gateway idle")
PY

if [ -e "$BACKUP" ]; then
    say "FAIL: backup already exists: $BACKUP"
    say "Refusing to overwrite a previous rollback point."
    exit 1
fi
cp -a "$HERMES_CONFIG" "$BACKUP"
say "PASS: backup created"

rollback_on_error() {
    rc=$?
    trap - ERR
    if [ "$rc" -ne 0 ]; then
        section "ERROR ROLLBACK"
        cp -a "$BACKUP" "$HERMES_CONFIG" || true
        systemctl --user restart hermes-gateway.service || true
        say "restored original Hermes config after failure"
    fi
    exit "$rc"
}
trap rollback_on_error ERR

section "SET HERMES REASONING EFFORT NONE"
"$HERMES_BIN" config set agent.reasoning_effort none

"$HERMES_PYTHON" - "$HERMES_CONFIG" <<'PY'
from pathlib import Path
import sys, yaml
cfg = yaml.safe_load(Path(sys.argv[1]).read_text(encoding="utf-8")) or {}
value = (cfg.get("agent") or {}).get("reasoning_effort")
assert str(value).strip().lower() == "none", value
print("PASS: config agent.reasoning_effort = none")
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
    say "FAIL: Hermes did not return active"
    exit 1
}
say "PASS: Hermes active after restart"

section "POSTCHECK"
"$HERMES_PYTHON" - "$HERMES_CONFIG" "$HERMES_HOME/gateway_state.json" <<'PY'
from pathlib import Path
import json, sys, yaml
cfg = yaml.safe_load(Path(sys.argv[1]).read_text(encoding="utf-8")) or {}
value = (cfg.get("agent") or {}).get("reasoning_effort")
print("agent.reasoning_effort:", value)
state_path = Path(sys.argv[2])
if state_path.exists():
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
        print("gateway_state:", json.dumps(state, ensure_ascii=False))
    except Exception as exc:
        print("gateway_state unreadable:", repr(exc))
PY

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

trap - ERR

echo
say "PASS: Hermes reasoning is disabled globally for Hermes sessions"
say "Backup: $BACKUP"
say "ROLLBACK: git show origin/feat/ai-gateway-scheduler:tools/rollback_hermes_reasoning_none_stage9.sh | bash"
