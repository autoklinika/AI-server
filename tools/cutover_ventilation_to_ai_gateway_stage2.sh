#!/usr/bin/env bash
set -euo pipefail

ROOT="${HOME}/AI-server"
BRANCH="feat/ai-gateway-scheduler"
WT="${HOME}/ai-server-gateway-stage2-cutover"
GATEWAY_DEPLOY="/opt/ai-gateway"
GATEWAY_ENV="/etc/ai-gateway/ai-gateway.env"
AI_ENV="/etc/ai-bridge/ai-bridge.env"
AI_ENV_BACKUP="/etc/ai-bridge/ai-bridge.env.pre-ai-gateway-stage2"
TARGET_OLLAMA_URL="http://127.0.0.1:11435/clients/ventilation"
DIRECT_OLLAMA_URL="http://127.0.0.1:11434"
BOOTSTRAP_PYTHON="/opt/ai-bridge/.venv/bin/python"
CUTOVER_APPLIED=0
SUCCESS=0

cleanup() {
    rc=$?
    trap - EXIT INT TERM
    if [ "$SUCCESS" -ne 1 ] && [ "$CUTOVER_APPLIED" -eq 1 ] && [ -r "$AI_ENV_BACKUP" ]; then
        echo
        echo "===== AUTOMATIC ROLLBACK ====="
        sudo cp -a "$AI_ENV_BACKUP" "$AI_ENV"
        echo "restored: $AI_ENV"
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
[ -r "$AI_ENV" ] || { echo "FAIL: AI Bridge env not readable: $AI_ENV"; exit 1; }
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

CURRENT_OLLAMA_URL="$(grep -E '^AI_BRIDGE_OLLAMA_URL=' "$AI_ENV" | tail -n 1 | cut -d= -f2- || true)"

echo
echo "===== PRECHECK ====="
echo "local branch:      $(git branch --show-current)"
echo "local HEAD:        $(git rev-parse HEAD)"
echo "ai-bridge:         $AI_STATE_BEFORE pid=$AI_PID_BEFORE"
echo "analysis timer:    $TIMER_STATE_BEFORE"
echo "ollama:            $OLLAMA_STATE_BEFORE"
echo "gateway:           $(systemctl is-active ai-gateway.service)"
echo "hermes:            $HERMES_STATE_BEFORE"
echo "current AI URL:    $CURRENT_OLLAMA_URL"
echo "target AI URL:     $TARGET_OLLAMA_URL"

[ "$AI_STATE_BEFORE" = "active" ] || { echo "FAIL: ai-bridge.service is not active"; exit 1; }
[ "$TIMER_STATE_BEFORE" = "active" ] || { echo "FAIL: analysis timer is not active"; exit 1; }
[ "$OLLAMA_STATE_BEFORE" = "active" ] || { echo "FAIL: ollama.service is not active"; exit 1; }

if [ "$CURRENT_OLLAMA_URL" != "$DIRECT_OLLAMA_URL" ] && [ "$CURRENT_OLLAMA_URL" != "$TARGET_OLLAMA_URL" ]; then
    echo "FAIL: unexpected current AI_BRIDGE_OLLAMA_URL=$CURRENT_OLLAMA_URL"
    exit 1
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
bash -n "$WT/tools/cutover_ventilation_to_ai_gateway_stage2.sh"
"$BOOTSTRAP_PYTHON" -m py_compile "$WT/src/ai_bridge/gateway/app.py"

echo
echo "===== UPDATE ISOLATED GATEWAY ====="
sudo systemctl stop ai-gateway.service
sudo rm -rf "$GATEWAY_DEPLOY"
sudo install -d -m 0755 -o harrypotter -g harrypotter "$GATEWAY_DEPLOY"
rsync -a \
    --exclude='.git' \
    --exclude='.venv' \
    --exclude='__pycache__' \
    "$WT/" "$GATEWAY_DEPLOY/"
"$BOOTSTRAP_PYTHON" -m venv "$GATEWAY_DEPLOY/.venv"
"$GATEWAY_DEPLOY/.venv/bin/python" -m pip install --disable-pip-version-check "$GATEWAY_DEPLOY"
[ -r "$GATEWAY_ENV" ] || { echo "FAIL: missing gateway env $GATEWAY_ENV"; exit 1; }
sudo install -m 0644 "$WT/deploy/systemd/ai-gateway.service" /etc/systemd/system/ai-gateway.service
sudo systemctl daemon-reload
sudo systemctl restart ai-gateway.service

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
        break
    fi
    sleep 0.2
done

"$GATEWAY_DEPLOY/.venv/bin/python" - <<'PY'
import json
import urllib.request
with urllib.request.urlopen("http://127.0.0.1:11435/health", timeout=3) as response:
    health = json.load(response)
assert health["status"] == "ok", health
with urllib.request.urlopen("http://127.0.0.1:11435/clients/ventilation/api/tags", timeout=3) as response:
    assert response.status == 200
print("PASS: dedicated ventilation route is reachable")
PY

echo
echo "===== BACKUP + CUTOVER CONFIG ====="
if [ "$CURRENT_OLLAMA_URL" != "$TARGET_OLLAMA_URL" ]; then
    if [ ! -e "$AI_ENV_BACKUP" ]; then
        sudo cp -a "$AI_ENV" "$AI_ENV_BACKUP"
        echo "backup created: $AI_ENV_BACKUP"
    else
        echo "backup preserved: $AI_ENV_BACKUP"
    fi
    sudo python3 - "$AI_ENV" "$TARGET_OLLAMA_URL" <<'PY'
from pathlib import Path
import sys
path = Path(sys.argv[1])
target = sys.argv[2]
lines = path.read_text(encoding="utf-8").splitlines()
out = []
found = False
for line in lines:
    if line.startswith("AI_BRIDGE_OLLAMA_URL="):
        if not found:
            out.append(f"AI_BRIDGE_OLLAMA_URL={target}")
            found = True
        continue
    out.append(line)
if not found:
    out.append(f"AI_BRIDGE_OLLAMA_URL={target}")
path.write_text("\n".join(out) + "\n", encoding="utf-8")
PY
    CUTOVER_APPLIED=1
else
    echo "configuration already points to ventilation gateway route"
fi

NEW_OLLAMA_URL="$(grep -E '^AI_BRIDGE_OLLAMA_URL=' "$AI_ENV" | tail -n 1 | cut -d= -f2-)"
[ "$NEW_OLLAMA_URL" = "$TARGET_OLLAMA_URL" ] || {
    echo "FAIL: cutover URL was not written correctly"
    exit 1
}
echo "AI_BRIDGE_OLLAMA_URL=$NEW_OLLAMA_URL"

echo
echo "===== REAL QWEN VIA PRODUCTION ROUTE ====="
set -a
# shellcheck disable=SC1090
. "$AI_ENV"
set +a
"$BOOTSTRAP_PYTHON" - <<'PY'
import json
import os
import urllib.request
base = os.environ["AI_BRIDGE_OLLAMA_URL"].rstrip("/")
payload = json.dumps({
    "model": os.environ.get("AI_BRIDGE_OLLAMA_MODEL", "qwen3.6:35b"),
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
assert wait_ms is not None, "missing wait time"
print(
    "PASS: production-config route -> gateway -> Qwen "
    f"job={job_id} priority={priority} wait_ms={wait_ms}"
)
PY

echo
echo "===== ANALYSIS SERVICE CHECK ====="
# If the timer happened to start the oneshot, allow it to finish before our check.
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
[ "$ANALYSIS_RESULT" = "success" ] && [ "$ANALYSIS_EXIT" = "0" ] || {
    echo "FAIL: production ventilation analysis service failed after cutover"
    journalctl -u ai-bridge-analysis.service -n 30 --no-pager || true
    exit 1
}

echo
echo "===== POSTCHECK ====="
AI_PID_AFTER="$(systemctl show ai-bridge.service -p MainPID --value 2>/dev/null || true)"
AI_STATE_AFTER="$(systemctl is-active ai-bridge.service 2>/dev/null || true)"
TIMER_STATE_AFTER="$(systemctl is-active ai-bridge-analysis.timer 2>/dev/null || true)"
OLLAMA_STATE_AFTER="$(systemctl is-active ollama.service 2>/dev/null || true)"
HERMES_STATE_AFTER="$(systemctl is-active hermes.service 2>/dev/null || true)"
GATEWAY_STATE_AFTER="$(systemctl is-active ai-gateway.service 2>/dev/null || true)"
echo "ai-bridge:      $AI_STATE_AFTER pid=$AI_PID_AFTER"
echo "analysis timer: $TIMER_STATE_AFTER"
echo "ollama:         $OLLAMA_STATE_AFTER"
echo "gateway:        $GATEWAY_STATE_AFTER"
echo "hermes:         $HERMES_STATE_AFTER"
echo "AI URL:         $NEW_OLLAMA_URL"

[ "$AI_PID_BEFORE" = "$AI_PID_AFTER" ] || { echo "FAIL: ai-bridge PID changed"; exit 1; }
[ "$AI_STATE_BEFORE" = "$AI_STATE_AFTER" ] || { echo "FAIL: ai-bridge state changed"; exit 1; }
[ "$TIMER_STATE_AFTER" = "active" ] || { echo "FAIL: analysis timer is not active"; exit 1; }
[ "$OLLAMA_STATE_AFTER" = "active" ] || { echo "FAIL: Ollama is not active"; exit 1; }
[ "$GATEWAY_STATE_AFTER" = "active" ] || { echo "FAIL: gateway is not active"; exit 1; }
[ "$HERMES_STATE_BEFORE" = "$HERMES_STATE_AFTER" ] || { echo "FAIL: Hermes state changed"; exit 1; }

SUCCESS=1
CUTOVER_APPLIED=0

echo
echo "PASS: ventilation analysis is routed through AI Gateway with priority 10"
echo "ROLLBACK: git show origin/$BRANCH:tools/rollback_ventilation_ai_gateway_stage2.sh | bash"
