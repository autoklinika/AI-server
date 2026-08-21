#!/usr/bin/env bash
set -euo pipefail

ROOT="${HOME}/AI-server"
BRANCH="agent/ai-advisory-no-alerts-stage1"
WT="${HOME}/ai-server-pr10-real-ollama-validation"
PYTHON="/opt/ai-bridge/.venv/bin/python"
ENV_FILE="/etc/ai-bridge/ai-bridge.env"

cleanup() {
    rc=$?
    trap - EXIT INT TERM
    if [ -d "$WT" ]; then
        git -C "$ROOT" worktree remove --force "$WT" >/dev/null 2>&1 || true
    fi
    exit "$rc"
}
trap cleanup EXIT INT TERM

echo "===== PR #10 REAL OLLAMA ALERT-BOUNDARY VALIDATION ====="

[ -d "$ROOT/.git" ] || {
    echo "FAIL: repository not found at $ROOT"
    exit 1
}
[ -x "$PYTHON" ] || {
    echo "FAIL: production Python not found at $PYTHON"
    exit 1
}
[ -r "$ENV_FILE" ] || {
    echo "FAIL: environment file not readable at $ENV_FILE"
    exit 1
}

cd "$ROOT"

echo
echo "===== PRODUCTION PRECHECK ====="
echo "local branch: $(git branch --show-current)"
echo "local HEAD:   $(git rev-parse HEAD)"
echo "origin main before fetch: $(git rev-parse origin/main 2>/dev/null || echo unknown)"
AI_PID_BEFORE="$(systemctl show ai-bridge.service -p MainPID --value 2>/dev/null || true)"
AI_STATE_BEFORE="$(systemctl is-active ai-bridge.service 2>/dev/null || true)"
TIMER_STATE_BEFORE="$(systemctl is-active ai-bridge-analysis.timer 2>/dev/null || true)"
OLLAMA_STATE="$(systemctl is-active ollama.service 2>/dev/null || true)"
echo "ai-bridge: $AI_STATE_BEFORE pid=$AI_PID_BEFORE"
echo "analysis timer: $TIMER_STATE_BEFORE"
echo "ollama: $OLLAMA_STATE"

[ "$OLLAMA_STATE" = "active" ] || {
    echo "FAIL: ollama.service is not active"
    exit 1
}

echo
echo "===== FETCH PR #10 ====="
git fetch origin main "$BRANCH"
echo "origin/main:   $(git rev-parse origin/main)"
echo "PR #10 HEAD:  $(git rev-parse "origin/$BRANCH")"

if [ -d "$WT" ]; then
    git worktree remove --force "$WT" >/dev/null 2>&1 || true
fi
git worktree add --detach "$WT" "origin/$BRANCH"

echo
echo "===== STATIC PRECHECK ====="
PYTHONPATH="$WT/src" "$PYTHON" -m py_compile \
    "$WT/src/ai_bridge/adapters/ventilation/analysis_v12_2.py" \
    "$WT/src/ai_bridge/analysis/service_v12_2.py" \
    "$WT/tools/validate_ai_advisory_no_alerts_real_ollama.py"
PYTHONPATH="$WT/src" "$PYTHON" - <<'PY'
from ai_bridge.adapters.ventilation.analysis_v12_2 import PROMPT_VERSION
assert PROMPT_VERSION == "ventilation-v12.2.1-no-alert-context", PROMPT_VERSION
print("PASS: PR #10 prompt profile =", PROMPT_VERSION)
PY

# Systemd EnvironmentFile syntax used by this deployment is compatible with the
# simple KEY=VALUE shell assignments stored in this file. Export values only for
# this validation process; do not print them.
set -a
# shellcheck disable=SC1090
. "$ENV_FILE"
set +a

echo
echo "===== REAL QWEN / OLLAMA VALIDATION ====="
PYTHONPATH="$WT/src" "$PYTHON" \
    "$WT/tools/validate_ai_advisory_no_alerts_real_ollama.py"

echo
echo "===== PRODUCTION POSTCHECK ====="
AI_PID_AFTER="$(systemctl show ai-bridge.service -p MainPID --value 2>/dev/null || true)"
AI_STATE_AFTER="$(systemctl is-active ai-bridge.service 2>/dev/null || true)"
TIMER_STATE_AFTER="$(systemctl is-active ai-bridge-analysis.timer 2>/dev/null || true)"
echo "ai-bridge: $AI_STATE_AFTER pid=$AI_PID_AFTER"
echo "analysis timer: $TIMER_STATE_AFTER"
echo "production /opt/ai-bridge was not modified"
echo "production database/cache were not used by the validator"

if [ "$AI_STATE_BEFORE" != "$AI_STATE_AFTER" ]; then
    echo "FAIL: ai-bridge service state changed during validation"
    exit 1
fi
if [ "$TIMER_STATE_BEFORE" != "$TIMER_STATE_AFTER" ]; then
    echo "FAIL: analysis timer state changed during validation"
    exit 1
fi

echo
echo "PASS: PR #10 validated with real Qwen/Ollama without production deployment"
