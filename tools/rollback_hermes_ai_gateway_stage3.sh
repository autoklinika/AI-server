#!/usr/bin/env bash
set -euo pipefail

HERMES_HOME="/srv/ai-data/hermes"
HERMES_CONFIG="${HERMES_HOME}/config.yaml"
HERMES_CONFIG_BACKUP="${HERMES_HOME}/config.yaml.pre-ai-gateway-stage3"
HERMES_SERVICE="hermes-gateway.service"
GATEWAY_DEPLOY="/opt/ai-gateway"
GATEWAY_BACKUP="/opt/ai-gateway.pre-stage3"
DIRECT_BASE_URL="http://192.168.1.55:11434/v1"
TARGET_BASE_URL="http://127.0.0.1:11435/clients/hermes/v1"
PYTHON="/opt/ai-bridge/.venv/bin/python"

echo "===== ROLLBACK HERMES FROM AI GATEWAY ====="

[ -r "$HERMES_CONFIG_BACKUP" ] || {
    echo "FAIL: Hermes config backup missing: $HERMES_CONFIG_BACKUP"
    exit 1
}
[ -d "$GATEWAY_BACKUP" ] || {
    echo "FAIL: gateway backup missing: $GATEWAY_BACKUP"
    exit 1
}
[ -x "$PYTHON" ] || {
    echo "FAIL: production Python missing: $PYTHON"
    exit 1
}

AI_PID_BEFORE="$(systemctl show ai-bridge.service -p MainPID --value 2>/dev/null || true)"
VENT_ROUTE_BEFORE="$(systemctl show ai-bridge-analysis.service -p Environment --value 2>/dev/null | tr ' ' '\n' | grep '^AI_BRIDGE_OLLAMA_URL=' | cut -d= -f2- || true)"

echo "restoring Hermes config: $HERMES_CONFIG_BACKUP"
cp -a "$HERMES_CONFIG_BACKUP" "$HERMES_CONFIG"

DIRECT_COUNT="$(grep -Fc "base_url: $DIRECT_BASE_URL" "$HERMES_CONFIG" || true)"
TARGET_COUNT="$(grep -Fc "base_url: $TARGET_BASE_URL" "$HERMES_CONFIG" || true)"
[ "$DIRECT_COUNT" -ge 1 ] || {
    echo "FAIL: restored Hermes config does not contain direct Ollama route"
    exit 1
}
[ "$TARGET_COUNT" -eq 0 ] || {
    echo "FAIL: restored Hermes config still contains scheduler route"
    exit 1
}

echo "restoring pre-stage3 gateway deployment"
sudo systemctl stop ai-gateway.service
sudo rm -rf "$GATEWAY_DEPLOY"
sudo cp -a "$GATEWAY_BACKUP" "$GATEWAY_DEPLOY"
sudo systemctl start ai-gateway.service

for _ in $(seq 1 60); do
    if "$PYTHON" - <<'PY' >/dev/null 2>&1
import json
import urllib.request
with urllib.request.urlopen("http://127.0.0.1:11435/health", timeout=1) as response:
    data = json.load(response)
assert data.get("status") == "ok", data
assert data.get("ollama") == "ok", data
with urllib.request.urlopen("http://127.0.0.1:11435/clients/ventilation/api/tags", timeout=1) as response:
    assert response.status == 200
PY
    then
        break
    fi
    sleep 0.25
done

systemctl --user restart "$HERMES_SERVICE"
for _ in $(seq 1 120); do
    if [ "$(systemctl --user is-active "$HERMES_SERVICE" 2>/dev/null || true)" = "active" ] \
        && "$PYTHON" - "$HERMES_HOME/gateway_state.json" <<'PY' >/dev/null 2>&1
import json
from pathlib import Path
import sys
data = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
assert data.get("gateway_state") == "running", data
platforms = data.get("platforms") or {}
assert (platforms.get("telegram") or {}).get("state") == "connected", data
PY
    then
        break
    fi
    sleep 0.5
done

AI_PID_AFTER="$(systemctl show ai-bridge.service -p MainPID --value 2>/dev/null || true)"
VENT_ROUTE_AFTER="$(systemctl show ai-bridge-analysis.service -p Environment --value 2>/dev/null | tr ' ' '\n' | grep '^AI_BRIDGE_OLLAMA_URL=' | cut -d= -f2- || true)"
HERMES_STATE="$(systemctl --user is-active "$HERMES_SERVICE" 2>/dev/null || true)"
GATEWAY_STATE="$(systemctl is-active ai-gateway.service 2>/dev/null || true)"

echo
echo "===== POSTCHECK ====="
echo "ai-bridge pid:     $AI_PID_AFTER"
echo "ventilation route: $VENT_ROUTE_AFTER"
echo "gateway:           $GATEWAY_STATE"
echo "Hermes:            $HERMES_STATE"
echo "Hermes route:      $DIRECT_BASE_URL"

[ "$AI_PID_BEFORE" = "$AI_PID_AFTER" ] || { echo "FAIL: ai-bridge PID changed"; exit 1; }
[ "$VENT_ROUTE_AFTER" = "$VENT_ROUTE_BEFORE" ] || { echo "FAIL: ventilation route changed"; exit 1; }
[ "$GATEWAY_STATE" = "active" ] || { echo "FAIL: gateway is not active"; exit 1; }
[ "$HERMES_STATE" = "active" ] || { echo "FAIL: Hermes is not active"; exit 1; }

echo
echo "PASS: Hermes restored to direct Ollama routing"
echo "Ventilation remains routed through the priority-10 gateway namespace"
