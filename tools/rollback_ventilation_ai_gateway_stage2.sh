#!/usr/bin/env bash
set -euo pipefail

AI_ENV="/etc/ai-bridge/ai-bridge.env"
AI_ENV_BACKUP="/etc/ai-bridge/ai-bridge.env.pre-ai-gateway-stage2"
DIRECT_OLLAMA_URL="http://127.0.0.1:11434"
PYTHON="/opt/ai-bridge/.venv/bin/python"

echo "===== ROLLBACK VENTILATION FROM AI GATEWAY ====="

[ -r "$AI_ENV_BACKUP" ] || {
    echo "FAIL: rollback backup missing: $AI_ENV_BACKUP"
    exit 1
}
[ -x "$PYTHON" ] || {
    echo "FAIL: production Python missing: $PYTHON"
    exit 1
}

AI_PID_BEFORE="$(systemctl show ai-bridge.service -p MainPID --value 2>/dev/null || true)"
HERMES_STATE_BEFORE="$(systemctl is-active hermes.service 2>/dev/null || true)"

echo "backup: $AI_ENV_BACKUP"
sudo cp -a "$AI_ENV_BACKUP" "$AI_ENV"

RESTORED_URL_RAW="$(grep -E '^AI_BRIDGE_OLLAMA_URL=' "$AI_ENV" | tail -n 1 | cut -d= -f2- || true)"
RESTORED_URL="${RESTORED_URL_RAW:-$DIRECT_OLLAMA_URL}"
if [ -n "$RESTORED_URL_RAW" ]; then
    echo "restored AI URL: $RESTORED_URL"
else
    echo "restored AI URL: $RESTORED_URL (implicit code default)"
fi
[ "$RESTORED_URL" = "$DIRECT_OLLAMA_URL" ] || {
    echo "FAIL: backup does not restore the expected direct Ollama URL"
    exit 1
}

"$PYTHON" - <<'PY'
import json
import urllib.request
with urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=3) as response:
    data = json.load(response)
assert isinstance(data, dict), data
print("PASS: direct Ollama endpoint reachable")
PY

AI_PID_AFTER="$(systemctl show ai-bridge.service -p MainPID --value 2>/dev/null || true)"
HERMES_STATE_AFTER="$(systemctl is-active hermes.service 2>/dev/null || true)"
TIMER_STATE="$(systemctl is-active ai-bridge-analysis.timer 2>/dev/null || true)"
GATEWAY_STATE="$(systemctl is-active ai-gateway.service 2>/dev/null || true)"

echo "ai-bridge pid:  $AI_PID_AFTER"
echo "analysis timer: $TIMER_STATE"
echo "gateway:        $GATEWAY_STATE (left running, but ventilation bypasses it)"
echo "hermes:         $HERMES_STATE_AFTER"

[ "$AI_PID_BEFORE" = "$AI_PID_AFTER" ] || { echo "FAIL: ai-bridge PID changed"; exit 1; }
[ "$TIMER_STATE" = "active" ] || { echo "FAIL: analysis timer is not active"; exit 1; }
[ "$HERMES_STATE_BEFORE" = "$HERMES_STATE_AFTER" ] || { echo "FAIL: Hermes state changed"; exit 1; }

echo
echo "PASS: ventilation restored to direct Ollama routing"
