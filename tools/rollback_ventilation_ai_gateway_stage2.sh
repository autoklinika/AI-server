#!/usr/bin/env bash
set -euo pipefail

ANALYSIS_DROPIN="/etc/systemd/system/ai-bridge-analysis.service.d/10-ai-gateway.conf"
PYTHON="/opt/ai-bridge/.venv/bin/python"
DIRECT_OLLAMA_URL="http://127.0.0.1:11434"

echo "===== ROLLBACK VENTILATION FROM AI GATEWAY ====="

[ -x "$PYTHON" ] || {
    echo "FAIL: production Python missing: $PYTHON"
    exit 1
}

AI_PID_BEFORE="$(systemctl show ai-bridge.service -p MainPID --value 2>/dev/null || true)"
HERMES_STATE_BEFORE="$(systemctl is-active hermes.service 2>/dev/null || true)"

if [ -e "$ANALYSIS_DROPIN" ]; then
    sudo rm -f "$ANALYSIS_DROPIN"
    sudo systemctl daemon-reload
    echo "removed: $ANALYSIS_DROPIN"
else
    echo "analysis gateway drop-in already absent"
fi

"$PYTHON" - <<'PY'
import json
import urllib.request
with urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=3) as response:
    data = json.load(response)
assert isinstance(data, dict), data
print("PASS: direct Ollama endpoint reachable")
PY

EFFECTIVE_EXEC="$(systemctl show ai-bridge-analysis.service -p ExecStart --value 2>/dev/null || true)"
case "$EFFECTIVE_EXEC" in
    *"AI_BRIDGE_OLLAMA_URL=http://127.0.0.1:11435/clients/ventilation"*)
        echo "FAIL: analysis service still contains gateway override"
        exit 1
        ;;
    *) ;;
esac

AI_PID_AFTER="$(systemctl show ai-bridge.service -p MainPID --value 2>/dev/null || true)"
HERMES_STATE_AFTER="$(systemctl is-active hermes.service 2>/dev/null || true)"
TIMER_STATE="$(systemctl is-active ai-bridge-analysis.timer 2>/dev/null || true)"
GATEWAY_STATE="$(systemctl is-active ai-gateway.service 2>/dev/null || true)"

echo "ai-bridge pid:  $AI_PID_AFTER"
echo "analysis timer: $TIMER_STATE"
echo "gateway:        $GATEWAY_STATE (left running, ventilation bypasses it)"
echo "hermes:         $HERMES_STATE_AFTER"
echo "analysis route: $DIRECT_OLLAMA_URL (code default)"

[ "$AI_PID_BEFORE" = "$AI_PID_AFTER" ] || { echo "FAIL: ai-bridge PID changed"; exit 1; }
[ "$TIMER_STATE" = "active" ] || { echo "FAIL: analysis timer is not active"; exit 1; }
[ "$HERMES_STATE_BEFORE" = "$HERMES_STATE_AFTER" ] || { echo "FAIL: Hermes state changed"; exit 1; }

echo
echo "PASS: ventilation analysis restored to direct Ollama routing"
