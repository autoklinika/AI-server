#!/usr/bin/env bash
set -euo pipefail

ROOT="${HOME}/AI-server"
BRANCH="feat/ai-gateway-scheduler"
WT="${HOME}/ai-server-gateway-real-validation"
PYTHON="/opt/ai-bridge/.venv/bin/python"
TEST_HOST="127.0.0.1"
TEST_PORT="11436"
TEST_URL="http://${TEST_HOST}:${TEST_PORT}"
LOG="/tmp/ai-gateway-real-validation.log"
GATEWAY_PID=""

cleanup() {
    rc=$?
    trap - EXIT INT TERM
    if [ -n "$GATEWAY_PID" ] && kill -0 "$GATEWAY_PID" >/dev/null 2>&1; then
        kill "$GATEWAY_PID" >/dev/null 2>&1 || true
        wait "$GATEWAY_PID" >/dev/null 2>&1 || true
    fi
    if [ -d "$WT" ]; then
        git -C "$ROOT" worktree remove --force "$WT" >/dev/null 2>&1 || true
    fi
    exit "$rc"
}
trap cleanup EXIT INT TERM

echo "===== AI GATEWAY REAL-SERVER VALIDATION ====="

[ -d "$ROOT/.git" ] || {
    echo "FAIL: repository not found at $ROOT"
    exit 1
}
[ -x "$PYTHON" ] || {
    echo "FAIL: production Python not found at $PYTHON"
    exit 1
}

cd "$ROOT"

echo
echo "===== PRODUCTION PRECHECK ====="
echo "local branch: $(git branch --show-current)"
echo "local HEAD:   $(git rev-parse HEAD)"
AI_PID_BEFORE="$(systemctl show ai-bridge.service -p MainPID --value 2>/dev/null || true)"
AI_STATE_BEFORE="$(systemctl is-active ai-bridge.service 2>/dev/null || true)"
TIMER_STATE_BEFORE="$(systemctl is-active ai-bridge-analysis.timer 2>/dev/null || true)"
OLLAMA_STATE_BEFORE="$(systemctl is-active ollama.service 2>/dev/null || true)"
HERMES_STATE_BEFORE="$(systemctl is-active hermes.service 2>/dev/null || true)"
echo "ai-bridge:      $AI_STATE_BEFORE pid=$AI_PID_BEFORE"
echo "analysis timer: $TIMER_STATE_BEFORE"
echo "ollama:         $OLLAMA_STATE_BEFORE"
echo "hermes:         $HERMES_STATE_BEFORE"

[ "$OLLAMA_STATE_BEFORE" = "active" ] || {
    echo "FAIL: ollama.service is not active"
    exit 1
}

if ss -ltn "sport = :${TEST_PORT}" | tail -n +2 | grep -q .; then
    echo "FAIL: validation port ${TEST_PORT} is already in use"
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
PYTHONPATH="$WT/src" "$PYTHON" -m py_compile \
    "$WT/src/ai_bridge/gateway/scheduler.py" \
    "$WT/src/ai_bridge/gateway/app.py" \
    "$WT/src/ai_bridge/gateway/main.py" \
    "$WT/src/ai_bridge/ollama/client.py"

echo
echo "===== START TEMPORARY GATEWAY ====="
: > "$LOG"
(
    cd "$WT"
    export PYTHONPATH="$WT/src"
    export AI_BRIDGE_GATEWAY_HOST="$TEST_HOST"
    export AI_BRIDGE_GATEWAY_PORT="$TEST_PORT"
    export AI_BRIDGE_GATEWAY_URL="$TEST_URL"
    export AI_BRIDGE_OLLAMA_URL="http://127.0.0.1:11434"
    export AI_BRIDGE_GATEWAY_MAX_CONCURRENCY=1
    export AI_BRIDGE_GATEWAY_MAX_QUEUE_SIZE=16
    exec "$PYTHON" -m ai_bridge.gateway.main
) >"$LOG" 2>&1 &
GATEWAY_PID=$!

for _ in $(seq 1 50); do
    if ! kill -0 "$GATEWAY_PID" >/dev/null 2>&1; then
        echo "FAIL: temporary gateway exited"
        cat "$LOG"
        exit 1
    fi
    if "$PYTHON" - "$TEST_URL" <<'PY' >/dev/null 2>&1
import json
import sys
import urllib.request

url = sys.argv[1] + "/health"
with urllib.request.urlopen(url, timeout=1) as response:
    data = json.load(response)
assert data["ollama"] == "ok", data
PY
    then
        break
    fi
    sleep 0.1
done

"$PYTHON" - "$TEST_URL" <<'PY'
import json
import sys
import urllib.request

base = sys.argv[1]
with urllib.request.urlopen(base + "/health", timeout=3) as response:
    health = json.load(response)
assert health["status"] == "ok", health
assert health["ollama"] == "ok", health
print("PASS: gateway health -> Ollama OK")

payload = json.dumps(
    {
        "model": "qwen3.6:35b",
        "messages": [
            {
                "role": "user",
                "content": "Odpowiedz dokładnie jednym tokenem tekstowym: GATEWAY_OK",
            }
        ],
        "stream": False,
        "think": False,
        "options": {"temperature": 0},
    }
).encode("utf-8")
request = urllib.request.Request(
    base + "/api/chat",
    data=payload,
    method="POST",
    headers={
        "Content-Type": "application/json",
        "X-AI-Priority": "10",
        "X-AI-Source": "real-server-validation",
    },
)
with urllib.request.urlopen(request, timeout=300) as response:
    body = json.load(response)
    priority = response.headers.get("X-AI-Gateway-Priority")
    job_id = response.headers.get("X-AI-Gateway-Job-Id")
    wait_ms = response.headers.get("X-AI-Gateway-Wait-Ms")
content = ((body.get("message") or {}).get("content") or "").strip()
assert "GATEWAY_OK" in content, body
assert priority == "10", priority
assert job_id, "missing gateway job id"
assert wait_ms is not None, "missing gateway wait time"
print(f"PASS: real Qwen through gateway job={job_id} priority={priority} wait_ms={wait_ms}")

with urllib.request.urlopen(base + "/status", timeout=3) as response:
    status = json.load(response)
assert status["active_count"] == 0, status
assert status["queued_count"] == 0, status
print("PASS: scheduler returned to idle")
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
echo "production /opt/ai-bridge was not modified"
echo "Hermes and ventilation routing were not changed"

[ "$AI_PID_BEFORE" = "$AI_PID_AFTER" ] || {
    echo "FAIL: ai-bridge PID changed during validation"
    exit 1
}
[ "$AI_STATE_BEFORE" = "$AI_STATE_AFTER" ] || {
    echo "FAIL: ai-bridge state changed during validation"
    exit 1
}
[ "$TIMER_STATE_BEFORE" = "$TIMER_STATE_AFTER" ] || {
    echo "FAIL: analysis timer state changed during validation"
    exit 1
}
[ "$OLLAMA_STATE_BEFORE" = "$OLLAMA_STATE_AFTER" ] || {
    echo "FAIL: ollama state changed during validation"
    exit 1
}
[ "$HERMES_STATE_BEFORE" = "$HERMES_STATE_AFTER" ] || {
    echo "FAIL: Hermes state changed during validation"
    exit 1
}

echo
echo "PASS: AI Gateway validated against real Ollama/Qwen without production cutover"
