#!/usr/bin/env bash
set -euo pipefail

ROOT="${HOME}/AI-server"
BRANCH="feat/ai-gateway-scheduler"
WT="${HOME}/ai-server-gateway-stage3-cutover"
GATEWAY_DEPLOY="/opt/ai-gateway"
GATEWAY_BACKUP="/opt/ai-gateway.pre-stage3"
HERMES_HOME="/srv/ai-data/hermes"
HERMES_CONFIG="${HERMES_HOME}/config.yaml"
HERMES_CONFIG_BACKUP="${HERMES_HOME}/config.yaml.pre-ai-gateway-stage3"
HERMES_PYTHON="${HERMES_HOME}/hermes-agent/venv/bin/python"
HERMES_SERVICE="hermes-gateway.service"
DIRECT_BASE_URL="http://192.168.1.55:11434/v1"
TARGET_BASE_URL="http://127.0.0.1:11435/clients/hermes/v1"
BOOTSTRAP_PYTHON="/opt/ai-bridge/.venv/bin/python"
GATEWAY_UPDATED=0
CONFIG_UPDATED=0
SUCCESS=0

restore_gateway() {
    if [ "$GATEWAY_UPDATED" -eq 1 ] && [ -d "$GATEWAY_BACKUP" ]; then
        echo "restoring previous gateway deployment"
        sudo systemctl stop ai-gateway.service >/dev/null 2>&1 || true
        sudo rm -rf "$GATEWAY_DEPLOY"
        sudo cp -a "$GATEWAY_BACKUP" "$GATEWAY_DEPLOY"
        sudo systemctl start ai-gateway.service >/dev/null 2>&1 || true
    fi
}

restore_hermes_config() {
    if [ "$CONFIG_UPDATED" -eq 1 ] && [ -r "$HERMES_CONFIG_BACKUP" ]; then
        echo "restoring Hermes config"
        cp -a "$HERMES_CONFIG_BACKUP" "$HERMES_CONFIG"
        systemctl --user restart "$HERMES_SERVICE" >/dev/null 2>&1 || true
    fi
}

cleanup() {
    rc=$?
    trap - EXIT INT TERM
    if [ "$SUCCESS" -ne 1 ] && { [ "$GATEWAY_UPDATED" -eq 1 ] || [ "$CONFIG_UPDATED" -eq 1 ]; }; then
        echo
        echo "===== AUTOMATIC ROLLBACK ====="
        restore_hermes_config
        restore_gateway
    fi
    if [ -d "$WT" ]; then
        git -C "$ROOT" worktree remove --force "$WT" >/dev/null 2>&1 || true
    fi
    exit "$rc"
}
trap cleanup EXIT INT TERM

wait_gateway() {
    for _ in $(seq 1 60); do
        if "$BOOTSTRAP_PYTHON" - <<'PY' >/dev/null 2>&1
import json
import urllib.request
with urllib.request.urlopen("http://127.0.0.1:11435/health", timeout=1) as response:
    data = json.load(response)
assert data.get("status") == "ok", data
assert data.get("ollama") == "ok", data
with urllib.request.urlopen("http://127.0.0.1:11435/clients/hermes/v1/models", timeout=1) as response:
    assert response.status == 200
PY
        then
            return 0
        fi
        sleep 0.25
    done
    return 1
}

wait_hermes() {
    for _ in $(seq 1 120); do
        if [ "$(systemctl --user is-active "$HERMES_SERVICE" 2>/dev/null || true)" = "active" ] \
            && "$BOOTSTRAP_PYTHON" - "$HERMES_HOME/gateway_state.json" <<'PY' >/dev/null 2>&1
import json
from pathlib import Path
import sys
p = Path(sys.argv[1])
data = json.loads(p.read_text(encoding="utf-8"))
assert data.get("gateway_state") == "running", data
platforms = data.get("platforms") or {}
assert (platforms.get("telegram") or {}).get("state") == "connected", data
assert (platforms.get("api_server") or {}).get("state") == "connected", data
PY
        then
            return 0
        fi
        sleep 0.5
    done
    return 1
}

echo "===== AI GATEWAY STAGE-3 HERMES CUTOVER ====="

[ -d "$ROOT/.git" ] || { echo "FAIL: repository not found at $ROOT"; exit 1; }
[ -x "$BOOTSTRAP_PYTHON" ] || { echo "FAIL: production Python not found"; exit 1; }
[ -x "$HERMES_PYTHON" ] || { echo "FAIL: Hermes Python not found: $HERMES_PYTHON"; exit 1; }
[ -r "$HERMES_CONFIG" ] || { echo "FAIL: Hermes config not readable: $HERMES_CONFIG"; exit 1; }
[ "$(systemctl is-active ai-gateway.service 2>/dev/null || true)" = "active" ] || {
    echo "FAIL: ai-gateway.service is not active"
    exit 1
}
[ "$(systemctl --user is-active "$HERMES_SERVICE" 2>/dev/null || true)" = "active" ] || {
    echo "FAIL: $HERMES_SERVICE is not active"
    exit 1
}

cd "$ROOT"

AI_PID_BEFORE="$(systemctl show ai-bridge.service -p MainPID --value 2>/dev/null || true)"
VENT_ROUTE_BEFORE="$(systemctl show ai-bridge-analysis.service -p Environment --value 2>/dev/null | tr ' ' '\n' | grep '^AI_BRIDGE_OLLAMA_URL=' | cut -d= -f2- || true)"
HERMES_PID_BEFORE="$(systemctl --user show "$HERMES_SERVICE" -p MainPID --value 2>/dev/null || true)"
SESSION_KEYS_BEFORE="$($BOOTSTRAP_PYTHON - "$HERMES_HOME/sessions/sessions.json" <<'PY'
import json
from pathlib import Path
import sys
p = Path(sys.argv[1])
if not p.exists():
    print(0)
else:
    data = json.loads(p.read_text(encoding="utf-8"))
    print(sum(1 for k in data if k.startswith("agent:main:telegram:dm:")))
PY
)"

CURRENT_COUNT="$(grep -Fc "base_url: $DIRECT_BASE_URL" "$HERMES_CONFIG" || true)"
TARGET_COUNT="$(grep -Fc "base_url: $TARGET_BASE_URL" "$HERMES_CONFIG" || true)"

MODEL="$($HERMES_PYTHON - "$HERMES_CONFIG" <<'PY'
from pathlib import Path
import sys
import yaml
cfg = yaml.safe_load(Path(sys.argv[1]).read_text(encoding="utf-8")) or {}
model_cfg = cfg.get("model") or {}
model = ""
if isinstance(model_cfg, str):
    model = model_cfg
elif isinstance(model_cfg, dict):
    model = str(model_cfg.get("default") or model_cfg.get("model") or "").strip()
if not model:
    providers = cfg.get("custom_providers") or []
    if isinstance(providers, list):
        for item in providers:
            if isinstance(item, dict) and item.get("model"):
                model = str(item["model"]).strip()
                break
print(model)
PY
)"

[ -n "$MODEL" ] || { echo "FAIL: could not resolve Hermes model from config"; exit 1; }

if [ "$CURRENT_COUNT" -eq 0 ] && [ "$TARGET_COUNT" -eq 0 ]; then
    echo "FAIL: Hermes config contains neither expected direct nor gateway base_url"
    exit 1
fi
if [ "$CURRENT_COUNT" -gt 0 ] && [ "$TARGET_COUNT" -gt 0 ]; then
    echo "FAIL: Hermes config is partially routed; refusing ambiguous cutover"
    exit 1
fi

if [ "$TARGET_COUNT" -gt 0 ]; then
    ROUTE_DISPLAY="$TARGET_BASE_URL (already configured)"
else
    ROUTE_DISPLAY="$DIRECT_BASE_URL"
fi

echo
echo "===== PRECHECK ====="
echo "local branch:       $(git branch --show-current)"
echo "local HEAD:         $(git rev-parse HEAD)"
echo "ai-bridge pid:      $AI_PID_BEFORE"
echo "ventilation route:  ${VENT_ROUTE_BEFORE:-unknown}"
echo "gateway:            $(systemctl is-active ai-gateway.service)"
echo "Hermes service:     $(systemctl --user is-active "$HERMES_SERVICE") pid=$HERMES_PID_BEFORE"
echo "Hermes model:       $MODEL"
echo "Hermes base_url:    $ROUTE_DISPLAY"
echo "Telegram DM routes: $SESSION_KEYS_BEFORE"
echo "target base_url:    $TARGET_BASE_URL"

[ "$SESSION_KEYS_BEFORE" -ge 2 ] || {
    echo "FAIL: expected at least two Telegram DM routing keys before cutover"
    exit 1
}

# Stage 2 must remain in force while Hermes is cut over.
[ "$VENT_ROUTE_BEFORE" = "http://127.0.0.1:11435/clients/ventilation" ] || {
    echo "FAIL: ventilation is not currently routed through its priority-10 gateway namespace"
    exit 1
}

echo
echo "===== FETCH FEATURE BRANCH ====="
git fetch origin main "$BRANCH"
echo "origin/main:  $(git rev-parse origin/main)"
echo "gateway HEAD: $(git rev-parse "origin/$BRANCH")"
if [ -d "$WT" ]; then
    git worktree remove --force "$WT" >/dev/null 2>&1 || true
fi
git worktree add --detach "$WT" "origin/$BRANCH"

echo
echo "===== STATIC PRECHECK ====="
bash -n "$WT/tools/cutover_hermes_to_ai_gateway_stage3.sh"
bash -n "$WT/tools/rollback_hermes_ai_gateway_stage3.sh"
"$BOOTSTRAP_PYTHON" -m py_compile \
    "$WT/src/ai_bridge/gateway/app.py" \
    "$WT/src/ai_bridge/gateway/scheduler.py"

echo
echo "===== UPDATE GATEWAY IN STABLE PATH ====="
sudo rm -rf "$GATEWAY_BACKUP"
sudo cp -a "$GATEWAY_DEPLOY" "$GATEWAY_BACKUP"
GATEWAY_UPDATED=1
sudo systemctl stop ai-gateway.service
sudo rsync -a --delete \
    --exclude='.git' \
    --exclude='.venv' \
    --exclude='__pycache__' \
    "$WT/" "$GATEWAY_DEPLOY/"
"$GATEWAY_DEPLOY/.venv/bin/python" -m pip install --disable-pip-version-check --no-deps --force-reinstall "$GATEWAY_DEPLOY"
sudo install -m 0644 "$WT/deploy/systemd/ai-gateway.service" /etc/systemd/system/ai-gateway.service
sudo systemctl daemon-reload
sudo systemctl start ai-gateway.service
wait_gateway || { echo "FAIL: updated gateway or Hermes namespace failed health check"; exit 1; }
echo "PASS: updated gateway healthy; Hermes namespace reachable"

echo
echo "===== REAL QWEN THROUGH HERMES NAMESPACE ====="
"$BOOTSTRAP_PYTHON" - "$MODEL" <<'PY'
import json
import sys
import urllib.request
model = sys.argv[1]
payload = json.dumps({
    "model": model,
    "messages": [{"role": "user", "content": "Odpowiedz jednym słowem: OK"}],
    "stream": False,
    "temperature": 0,
}).encode("utf-8")
request = urllib.request.Request(
    "http://127.0.0.1:11435/clients/hermes/v1/chat/completions",
    data=payload,
    method="POST",
    headers={"Content-Type": "application/json"},
)
with urllib.request.urlopen(request, timeout=300) as response:
    body = json.load(response)
    priority = response.headers.get("X-AI-Gateway-Priority")
    job_id = response.headers.get("X-AI-Gateway-Job-Id")
    wait_ms = response.headers.get("X-AI-Gateway-Wait-Ms")
assert priority == "50", priority
assert job_id, "missing gateway job id"
assert wait_ms is not None, "missing wait time"
assert isinstance(body.get("choices"), list) and body["choices"], body
print(f"PASS: Hermes namespace -> Qwen job={job_id} priority={priority} wait_ms={wait_ms}")
PY

echo
echo "===== BACKUP + ROUTE HERMES CONFIG ====="
if [ "$TARGET_COUNT" -eq 0 ]; then
    if [ ! -e "$HERMES_CONFIG_BACKUP" ]; then
        cp -a "$HERMES_CONFIG" "$HERMES_CONFIG_BACKUP"
        echo "backup created: $HERMES_CONFIG_BACKUP"
    else
        echo "backup preserved: $HERMES_CONFIG_BACKUP"
    fi

    "$BOOTSTRAP_PYTHON" - "$HERMES_CONFIG" "$DIRECT_BASE_URL" "$TARGET_BASE_URL" <<'PY'
from pathlib import Path
import sys
path = Path(sys.argv[1])
old = sys.argv[2]
new = sys.argv[3]
text = path.read_text(encoding="utf-8")
needle = f"base_url: {old}"
replacement = f"base_url: {new}"
count = text.count(needle)
if count < 1:
    raise SystemExit("expected direct Hermes base_url not found")
text = text.replace(needle, replacement)
path.write_text(text, encoding="utf-8")
print(f"updated {count} Hermes base_url entries")
PY
    CONFIG_UPDATED=1
else
    echo "Hermes config already points to gateway namespace"
fi

OLD_LEFT="$(grep -Fc "base_url: $DIRECT_BASE_URL" "$HERMES_CONFIG" || true)"
NEW_COUNT="$(grep -Fc "base_url: $TARGET_BASE_URL" "$HERMES_CONFIG" || true)"
[ "$OLD_LEFT" -eq 0 ] || { echo "FAIL: direct Ollama base_url remains in Hermes config"; exit 1; }
[ "$NEW_COUNT" -ge 1 ] || { echo "FAIL: gateway base_url was not written to Hermes config"; exit 1; }
echo "PASS: Hermes config routes $NEW_COUNT local endpoint entries through scheduler"

echo
echo "===== RESTART HERMES USER SERVICE ====="
systemctl --user restart "$HERMES_SERVICE"
wait_hermes || {
    echo "FAIL: Hermes did not return to running + Telegram connected state"
    systemctl --user --no-pager --full status "$HERMES_SERVICE" || true
    journalctl --user -u "$HERMES_SERVICE" -n 60 --no-pager || true
    exit 1
}
HERMES_PID_AFTER="$(systemctl --user show "$HERMES_SERVICE" -p MainPID --value 2>/dev/null || true)"
echo "PASS: Hermes restarted and Telegram reconnected pid=$HERMES_PID_AFTER"

SESSION_KEYS_AFTER="$($BOOTSTRAP_PYTHON - "$HERMES_HOME/sessions/sessions.json" <<'PY'
import json
from pathlib import Path
import sys
p = Path(sys.argv[1])
data = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
print(sum(1 for k in data if k.startswith("agent:main:telegram:dm:")))
PY
)"
[ "$SESSION_KEYS_AFTER" -ge "$SESSION_KEYS_BEFORE" ] || {
    echo "FAIL: Telegram DM routing keys decreased after Hermes restart"
    exit 1
}

echo
echo "===== POSTCHECK ====="
AI_PID_AFTER="$(systemctl show ai-bridge.service -p MainPID --value 2>/dev/null || true)"
VENT_ROUTE_AFTER="$(systemctl show ai-bridge-analysis.service -p Environment --value 2>/dev/null | tr ' ' '\n' | grep '^AI_BRIDGE_OLLAMA_URL=' | cut -d= -f2- || true)"
echo "ai-bridge pid:      $AI_PID_AFTER"
echo "ventilation route:  $VENT_ROUTE_AFTER"
echo "gateway:            $(systemctl is-active ai-gateway.service)"
echo "Hermes:             $(systemctl --user is-active "$HERMES_SERVICE") pid=$HERMES_PID_AFTER"
echo "Hermes route:       $TARGET_BASE_URL"
echo "Telegram DM routes: $SESSION_KEYS_AFTER"

[ "$AI_PID_BEFORE" = "$AI_PID_AFTER" ] || { echo "FAIL: ai-bridge PID changed"; exit 1; }
[ "$VENT_ROUTE_AFTER" = "$VENT_ROUTE_BEFORE" ] || { echo "FAIL: ventilation route changed"; exit 1; }
[ "$(systemctl is-active ai-gateway.service 2>/dev/null || true)" = "active" ] || { echo "FAIL: gateway is not active"; exit 1; }
[ "$(systemctl --user is-active "$HERMES_SERVICE" 2>/dev/null || true)" = "active" ] || { echo "FAIL: Hermes is not active"; exit 1; }

SUCCESS=1
CONFIG_UPDATED=0
GATEWAY_UPDATED=0

echo
echo "PASS: Hermes is routed through AI Gateway with priority 50"
echo "Ventilation remains priority 10 and main ai-bridge.service was not changed"
echo "Hermes config backup: $HERMES_CONFIG_BACKUP"
echo "Gateway backup:       $GATEWAY_BACKUP"
echo "ROLLBACK: git show origin/$BRANCH:tools/rollback_hermes_ai_gateway_stage3.sh | bash"
