#!/usr/bin/env bash
set -euo pipefail

ROOT="${HOME}/AI-server"
BRANCH="feat/ai-gateway-scheduler"
WT="${HOME}/ai-server-gateway-stage1-install"
DEPLOY_DIR="/opt/ai-gateway"
ENV_DIR="/etc/ai-gateway"
ENV_FILE="${ENV_DIR}/ai-gateway.env"
UNIT_FILE="/etc/systemd/system/ai-gateway.service"
BOOTSTRAP_PYTHON="/opt/ai-bridge/.venv/bin/python"

cleanup() {
    rc=$?
    trap - EXIT INT TERM
    if [ -d "$WT" ]; then
        git -C "$ROOT" worktree remove --force "$WT" >/dev/null 2>&1 || true
    fi
    exit "$rc"
}
trap cleanup EXIT INT TERM

echo "===== AI GATEWAY STAGE-1 INSTALL ====="

[ -d "$ROOT/.git" ] || {
    echo "FAIL: repository not found at $ROOT"
    exit 1
}
[ -x "$BOOTSTRAP_PYTHON" ] || {
    echo "FAIL: production Python not found at $BOOTSTRAP_PYTHON"
    exit 1
}

cd "$ROOT"

AI_PID_BEFORE="$(systemctl show ai-bridge.service -p MainPID --value 2>/dev/null || true)"
AI_STATE_BEFORE="$(systemctl is-active ai-bridge.service 2>/dev/null || true)"
TIMER_STATE_BEFORE="$(systemctl is-active ai-bridge-analysis.timer 2>/dev/null || true)"
OLLAMA_STATE_BEFORE="$(systemctl is-active ollama.service 2>/dev/null || true)"
HERMES_STATE_BEFORE="$(systemctl is-active hermes.service 2>/dev/null || true)"

echo
echo "===== PRODUCTION PRECHECK ====="
echo "local branch:   $(git branch --show-current)"
echo "local HEAD:     $(git rev-parse HEAD)"
echo "ai-bridge:      $AI_STATE_BEFORE pid=$AI_PID_BEFORE"
echo "analysis timer: $TIMER_STATE_BEFORE"
echo "ollama:         $OLLAMA_STATE_BEFORE"
echo "hermes:         $HERMES_STATE_BEFORE"

[ "$AI_STATE_BEFORE" = "active" ] || {
    echo "FAIL: ai-bridge.service is not active"
    exit 1
}
[ "$OLLAMA_STATE_BEFORE" = "active" ] || {
    echo "FAIL: ollama.service is not active"
    exit 1
}

if ss -ltn "sport = :11435" | tail -n +2 | grep -q .; then
    if [ "$(systemctl is-active ai-gateway.service 2>/dev/null || true)" != "active" ]; then
        echo "FAIL: port 11435 is already in use by another process"
        exit 1
    fi
fi

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
bash -n "$WT/tools/install_ai_gateway_stage1.sh"
"$BOOTSTRAP_PYTHON" -m py_compile \
    "$WT/src/ai_bridge/gateway/scheduler.py" \
    "$WT/src/ai_bridge/gateway/app.py" \
    "$WT/src/ai_bridge/gateway/main.py"

echo
echo "===== INSTALL ISOLATED GATEWAY CODE ====="
sudo systemctl stop ai-gateway.service >/dev/null 2>&1 || true
sudo rm -rf "$DEPLOY_DIR"
sudo install -d -m 0755 -o harrypotter -g harrypotter "$DEPLOY_DIR"
rsync -a \
    --exclude='.git' \
    --exclude='.venv' \
    --exclude='__pycache__' \
    "$WT/" "$DEPLOY_DIR/"

"$BOOTSTRAP_PYTHON" -m venv "$DEPLOY_DIR/.venv"
"$DEPLOY_DIR/.venv/bin/python" -m pip install --disable-pip-version-check "$DEPLOY_DIR"

echo
echo "===== INSTALL ISOLATED CONFIG ====="
sudo install -d -m 0755 "$ENV_DIR"
if [ ! -e "$ENV_FILE" ]; then
    sudo install -m 0644 "$WT/deploy/ai-gateway.env.example" "$ENV_FILE"
    echo "created: $ENV_FILE"
else
    echo "preserved existing: $ENV_FILE"
fi
sudo install -m 0644 "$WT/deploy/systemd/ai-gateway.service" "$UNIT_FILE"
sudo systemctl daemon-reload
sudo systemctl enable --now ai-gateway.service

for _ in $(seq 1 50); do
    if "$DEPLOY_DIR/.venv/bin/python" - <<'PY' >/dev/null 2>&1
import json
import urllib.request
with urllib.request.urlopen("http://127.0.0.1:11435/health", timeout=1) as response:
    data = json.load(response)
assert data.get("status") == "ok", data
assert data.get("ollama") == "ok", data
PY
    then
        break
    fi
    sleep 0.2
done

echo
echo "===== GATEWAY VERIFY ====="
systemctl --no-pager --full status ai-gateway.service | sed -n '1,12p'
"$DEPLOY_DIR/.venv/bin/python" - <<'PY'
import json
import urllib.request
for path in ("/health", "/status"):
    with urllib.request.urlopen("http://127.0.0.1:11435" + path, timeout=3) as response:
        data = json.load(response)
    print(path, json.dumps(data, ensure_ascii=False, sort_keys=True))
PY

echo
echo "===== PRODUCTION POSTCHECK ====="
AI_PID_AFTER="$(systemctl show ai-bridge.service -p MainPID --value 2>/dev/null || true)"
AI_STATE_AFTER="$(systemctl is-active ai-bridge.service 2>/dev/null || true)"
TIMER_STATE_AFTER="$(systemctl is-active ai-bridge-analysis.timer 2>/dev/null || true)"
OLLAMA_STATE_AFTER="$(systemctl is-active ollama.service 2>/dev/null || true)"
HERMES_STATE_AFTER="$(systemctl is-active hermes.service 2>/dev/null || true)"
echo "ai-bridge:      $AI_STATE_AFTER pid=$AI_PID_AFTER"
echo "analysis timer: $TIMER_STATE_AFTER"
echo "ollama:         $OLLAMA_STATE_AFTER"
echo "hermes:         $HERMES_STATE_AFTER"
echo "gateway:        $(systemctl is-active ai-gateway.service 2>/dev/null || true)"
echo "production /opt/ai-bridge was not modified"
echo "ventilation and Hermes routing were not changed"

[ "$AI_PID_BEFORE" = "$AI_PID_AFTER" ] || {
    echo "FAIL: ai-bridge PID changed during gateway installation"
    exit 1
}
[ "$AI_STATE_BEFORE" = "$AI_STATE_AFTER" ] || {
    echo "FAIL: ai-bridge state changed during gateway installation"
    exit 1
}
[ "$TIMER_STATE_BEFORE" = "$TIMER_STATE_AFTER" ] || {
    echo "FAIL: analysis timer state changed during gateway installation"
    exit 1
}
[ "$OLLAMA_STATE_BEFORE" = "$OLLAMA_STATE_AFTER" ] || {
    echo "FAIL: Ollama state changed during gateway installation"
    exit 1
}
[ "$HERMES_STATE_BEFORE" = "$HERMES_STATE_AFTER" ] || {
    echo "FAIL: Hermes state changed during gateway installation"
    exit 1
}
[ "$(systemctl is-active ai-gateway.service 2>/dev/null || true)" = "active" ] || {
    echo "FAIL: ai-gateway.service is not active"
    exit 1
}

echo
echo "PASS: isolated AI Gateway installed on 127.0.0.1:11435 without production cutover"
