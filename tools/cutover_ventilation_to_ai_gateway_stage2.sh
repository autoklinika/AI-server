#!/usr/bin/env bash
set -euo pipefail

ROOT="${HOME}/AI-server"
BRANCH="feat/ai-gateway-scheduler"
WT="${HOME}/ai-server-gateway-stage2-cutover"
GATEWAY_DEPLOY="/opt/ai-gateway"
GATEWAY_BACKUP="/opt/ai-gateway.pre-stage2"
UNIT_FILE="/etc/systemd/system/ai-gateway.service"
UNIT_BACKUP="/etc/systemd/system/ai-gateway.service.pre-stage2"
ANALYSIS_DROPIN_DIR="/etc/systemd/system/ai-bridge-analysis.service.d"
ANALYSIS_DROPIN="${ANALYSIS_DROPIN_DIR}/10-ai-gateway.conf"
TARGET_OLLAMA_URL="http://127.0.0.1:11435/clients/ventilation"
BOOTSTRAP_PYTHON="/opt/ai-bridge/.venv/bin/python"
GATEWAY_UPDATED=0
ROUTE_APPLIED=0
SUCCESS=0

restore_route() {
    if [ "$ROUTE_APPLIED" -eq 1 ]; then
        echo "restoring direct Ollama routing for ventilation analysis"
        sudo rm -f "$ANALYSIS_DROPIN"
        sudo systemctl daemon-reload
    fi
}

restore_gateway() {
    if [ "$GATEWAY_UPDATED" -eq 1 ] && [ -d "$GATEWAY_BACKUP" ]; then
        echo "restoring previous gateway deployment"
        sudo systemctl stop ai-gateway.service >/dev/null 2>&1 || true
        sudo rm -rf "$GATEWAY_DEPLOY"
        sudo mv "$GATEWAY_BACKUP" "$GATEWAY_DEPLOY"
        if [ -r "$UNIT_BACKUP" ]; then
            sudo cp -a "$UNIT_BACKUP" "$UNIT_FILE"
        fi
        sudo systemctl daemon-reload
        sudo systemctl start ai-gateway.service >/dev/null 2>&1 || true
    fi
}

cleanup() {
    rc=$?
    trap - EXIT INT TERM
    if [ "$SUCCESS" -ne 1 ] && { [ "$ROUTE_APPLIED" -eq 1 ] || [ "$GATEWAY_UPDATED" -eq 1 ]; }; then
        echo
        echo "===== AUTOMATIC ROLLBACK ====="
        restore_route
        restore_gateway
    fi
    if [ -d "$WT" ]; then
        git -C "$ROOT" worktree remove --force "$WT" >/dev/null 2>&1 || true
    fi
    exit "$rc"
}
trap cleanup EXIT INT TERM

echo "===== AI GATEWAY STAGE-2 VENTILATION CUTOVER ====="

[ -d "$ROOT/.git" ] || { echo "FAIL: repository not found at $ROOT"; exit 1; }
[ -x "$BOOTSTRAP_PYTHON" ] || { echo "FAIL: production Python not found"; exit 1; }
[ -d "$GATEWAY_DEPLOY" ] || { echo "FAIL: gateway deployment missing: $GATEWAY_DEPLOY"; exit 1; }
[ -r "$UNIT_FILE" ] || { echo "FAIL: gateway systemd unit missing: $UNIT_FILE"; exit 1; }
[ "$(systemctl is-active ai-gateway.service 2>/dev/null || true)" = "active" ] || {
    echo "FAIL: ai-gateway.service is not active"
    exit 1
}

cd "$ROOT"

AI_PID_BEFORE="$(systemctl show ai-bridge.service -p MainPID --value 2>/dev/null || true)"
AI_STATE_BEFORE="$(systemctl is-active ai-bridge.service 2>/dev/null || true)"
TIMER_STATE_BEFORE="$(systemctl is-active ai-bridge-analysis.timer 2>/dev/null || true)"
OLLAMA_STATE_BEFORE="$(systemctl is-active ollama.service 2>/dev/null || true)"
HERMES_STATE_BEFORE="$(systemctl is-active hermes.service 2>/dev/null || true)"

printf '\n===== PRECHECK =====\n'
printf 'local branch:      %s\n' "$(git branch --show-current)"
printf 'local HEAD:        %s\n' "$(git rev-parse HEAD)"
printf 'ai-bridge:         %s pid=%s\n' "$AI_STATE_BEFORE" "$AI_PID_BEFORE"
printf 'analysis timer:    %s\n' "$TIMER_STATE_BEFORE"
printf 'ollama:            %s\n' "$OLLAMA_STATE_BEFORE"
printf 'gateway:           %s\n' "$(systemctl is-active ai-gateway.service)"
printf 'hermes:            %s\n' "$HERMES_STATE_BEFORE"
printf 'ventilation route: direct Ollama (current)\n'
printf 'target route:      %s\n' "$TARGET_OLLAMA_URL"

[ "$AI_STATE_BEFORE" = "active" ] || { echo "FAIL: ai-bridge.service is not active"; exit 1; }
[ "$TIMER_STATE_BEFORE" = "active" ] || { echo "FAIL: analysis timer is not active"; exit 1; }
[ "$OLLAMA_STATE_BEFORE" = "active" ] || { echo "FAIL: ollama.service is not active"; exit 1; }
if [ -e "$ANALYSIS_DROPIN" ]; then
    echo "FAIL: analysis gateway drop-in already exists: $ANALYSIS_DROPIN"
    exit 1
fi

printf '\n===== FETCH FEATURE BRANCH =====\n'
git fetch origin main "$BRANCH"
printf 'origin/main:  %s\n' "$(git rev-parse origin/main)"
printf 'gateway HEAD: %s\n' "$(git rev-parse "origin/$BRANCH")"
if [ -d "$WT" ]; then
    git worktree remove --force "$WT" >/dev/null 2>&1 || true
fi
git worktree add --detach "$WT" "origin/$BRANCH"

printf '\n===== STATIC PRECHECK =====\n'
bash -n "$WT/tools/cutover_ventilation_to_ai_gateway_stage2.sh"
"$BOOTSTRAP_PYTHON" -m py_compile \
    "$WT/src/ai_bridge/gateway/app.py" \
    "$WT/src/ai_bridge/gateway/scheduler.py" \
    "$WT/src/ai_bridge/gateway/main.py"

printf '\n===== UPDATE GATEWAY IN STABLE PATH =====\n'
sudo rm -rf "$GATEWAY_BACKUP"
sudo cp -a "$GATEWAY_DEPLOY" "$GATEWAY_BACKUP"
sudo cp -a "$UNIT_FILE" "$UNIT_BACKUP"
GATEWAY_UPDATED=1

sudo systemctl stop ai-gateway.service
rsync -a --delete \
    --exclude='.git' \
    --exclude='.venv' \
    --exclude='__pycache__' \
    "$WT/" "$GATEWAY_DEPLOY/"
"$GATEWAY_DEPLOY/.venv/bin/python" -m pip install \
    --disable-pip-version-check \
    --no-deps \
    --force-reinstall \
    "$GATEWAY_DEPLOY"
sudo install -m 0644 "$WT/deploy/systemd/ai-gateway.service" "$UNIT_FILE"
sudo systemctl daemon-reload
sudo systemctl start ai-gateway.service

GATEWAY_HEALTHY=0
for _ in $(seq 1 50); do
    if "$GATEWAY_DEPLOY/.venv/bin/python" - <<'PY' >/dev/null 2>&1
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
        GATEWAY_HEALTHY=1
        break
    fi
    sleep 0.2
done
if [ "$GATEWAY_HEALTHY" -ne 1 ]; then
    echo "FAIL: updated gateway failed health check"
    systemctl --no-pager --full status ai-gateway.service || true
    journalctl -u ai-gateway.service -n 40 --no-pager || true
    exit 1
fi
echo "PASS: updated gateway healthy; ventilation route reachable"

printf '\n===== REAL QWEN THROUGH VENTILATION ROUTE =====\n'
"$GATEWAY_DEPLOY/.venv/bin/python" - "$TARGET_OLLAMA_URL" <<'PY'
import json
import sys
import urllib.request
base = sys.argv[1].rstrip("/")
payload = json.dumps({
    "model": "qwen3.6:35b",
    "messages": [{"role": "user", "content": "Zwróć krótki JSON potwierdzający test infrastruktury."}],
    "stream": False,
    "think": False,
    "format": {
        "type": "object",
        "properties": {"ok": {"type": "boolean"}},
        "required": ["ok"],
        "additionalProperties": False,
    },
    "options": {"temperature": 0},
}).encode("utf-8")
request = urllib.request.Request(
    base + "/api/chat",
    data=payload,
    method="POST",
    headers={"Content-Type": "application/json"},
)
with urllib.request.urlopen(request, timeout=300) as response:
    body = json.load(response)
    priority = response.headers.get("X-AI-Gateway-Priority")
    job_id = response.headers.get("X-AI-Gateway-Job-Id")
    wait_ms = response.headers.get("X-AI-Gateway-Wait-Ms")
assert body.get("done") is True, body
assert int(body.get("prompt_eval_count") or 0) > 0, body
assert priority == "10", priority
assert job_id, "missing gateway job id"
assert wait_ms is not None, "missing gateway wait time"
print(f"PASS: gateway -> Qwen job={job_id} priority={priority} wait_ms={wait_ms}")
PY

printf '\n===== APPLY ANALYSIS-ONLY ROUTE =====\n'
sudo install -d -m 0755 "$ANALYSIS_DROPIN_DIR"
printf '%s\n' \
    '[Service]' \
    'ExecStart=' \
    "ExecStart=/usr/bin/env AI_BRIDGE_OLLAMA_URL=${TARGET_OLLAMA_URL} /opt/ai-bridge/.venv/bin/ai-bridge-analyze-ventilation" \
    | sudo tee "$ANALYSIS_DROPIN" >/dev/null
ROUTE_APPLIED=1
sudo systemctl daemon-reload

echo "drop-in: $ANALYSIS_DROPIN"
systemctl cat ai-bridge-analysis.service | tail -n 8
EFFECTIVE_EXEC="$(systemctl show ai-bridge-analysis.service -p ExecStart --value)"
case "$EFFECTIVE_EXEC" in
    *"AI_BRIDGE_OLLAMA_URL=${TARGET_OLLAMA_URL}"*) ;;
    *) echo "FAIL: analysis service does not contain gateway route"; exit 1 ;;
esac

echo "PASS: only ai-bridge-analysis.service is routed through gateway"

printf '\n===== ANALYSIS SERVICE CHECK =====\n'
for _ in $(seq 1 600); do
    if [ "$(systemctl is-active ai-bridge-analysis.service 2>/dev/null || true)" != "active" ]; then
        break
    fi
    sleep 0.5
done
sudo systemctl start ai-bridge-analysis.service
ANALYSIS_RESULT="$(systemctl show ai-bridge-analysis.service -p Result --value 2>/dev/null || true)"
ANALYSIS_EXIT="$(systemctl show ai-bridge-analysis.service -p ExecMainStatus --value 2>/dev/null || true)"
echo "analysis result: $ANALYSIS_RESULT"
echo "analysis exit:   $ANALYSIS_EXIT"
if [ "$ANALYSIS_RESULT" != "success" ] || [ "$ANALYSIS_EXIT" != "0" ]; then
    echo "FAIL: production ventilation analysis service failed after cutover"
    journalctl -u ai-bridge-analysis.service -n 40 --no-pager || true
    exit 1
fi

printf '\n===== POSTCHECK =====\n'
AI_PID_AFTER="$(systemctl show ai-bridge.service -p MainPID --value 2>/dev/null || true)"
AI_STATE_AFTER="$(systemctl is-active ai-bridge.service 2>/dev/null || true)"
TIMER_STATE_AFTER="$(systemctl is-active ai-bridge-analysis.timer 2>/dev/null || true)"
OLLAMA_STATE_AFTER="$(systemctl is-active ollama.service 2>/dev/null || true)"
HERMES_STATE_AFTER="$(systemctl is-active hermes.service 2>/dev/null || true)"
GATEWAY_STATE_AFTER="$(systemctl is-active ai-gateway.service 2>/dev/null || true)"
printf 'ai-bridge:      %s pid=%s\n' "$AI_STATE_AFTER" "$AI_PID_AFTER"
printf 'analysis timer: %s\n' "$TIMER_STATE_AFTER"
printf 'ollama:         %s\n' "$OLLAMA_STATE_AFTER"
printf 'gateway:        %s\n' "$GATEWAY_STATE_AFTER"
printf 'hermes:         %s\n' "$HERMES_STATE_AFTER"
printf 'analysis route: %s\n' "$TARGET_OLLAMA_URL"

[ "$AI_PID_BEFORE" = "$AI_PID_AFTER" ] || { echo "FAIL: ai-bridge PID changed"; exit 1; }
[ "$AI_STATE_BEFORE" = "$AI_STATE_AFTER" ] || { echo "FAIL: ai-bridge state changed"; exit 1; }
[ "$TIMER_STATE_AFTER" = "active" ] || { echo "FAIL: analysis timer is not active"; exit 1; }
[ "$OLLAMA_STATE_AFTER" = "active" ] || { echo "FAIL: Ollama is not active"; exit 1; }
[ "$GATEWAY_STATE_AFTER" = "active" ] || { echo "FAIL: gateway is not active"; exit 1; }
[ "$HERMES_STATE_BEFORE" = "$HERMES_STATE_AFTER" ] || { echo "FAIL: Hermes state changed"; exit 1; }

SUCCESS=1
ROUTE_APPLIED=0
GATEWAY_UPDATED=0

echo
echo "PASS: ventilation analysis is routed through AI Gateway with priority 10"
echo "main ai-bridge.service configuration was not changed"
echo "previous gateway kept at: $GATEWAY_BACKUP"
echo "ROLLBACK ROUTE: git show origin/$BRANCH:tools/rollback_ventilation_ai_gateway_stage2.sh | bash"
