#!/usr/bin/env bash
set -euo pipefail

CURRENT="/opt/ai-platform/current"
STATE_FILE="/var/lib/ai-platform/stage-d/previous-release"
TIMER="ai-bridge-analysis.timer"
BRIDGE_HEALTH_URL="${AI_BRIDGE_HEALTH_URL:-}"
GATEWAY_HEALTH_URL="${AI_GATEWAY_HEALTH_URL:-http://127.0.0.1:11435/health}"
TIMER_WAS_ACTIVE=0

say(){ printf '%s\n' "$*"; }
fail(){ say "FAIL: $*" >&2; exit 1; }

resolve_bridge_health_url() {
  if [[ -n "$BRIDGE_HEALTH_URL" ]]; then
    return 0
  fi
  local bind_host
  bind_host="$(
    systemctl show ai-bridge.service -p Environment --value \
      | tr ' ' '\n' \
      | sed -n 's/^AI_BRIDGE_HOST=//p' \
      | tail -1
  )"
  case "$bind_host" in
    ""|"0.0.0.0"|"::"|"[::]") bind_host="127.0.0.1" ;;
  esac
  BRIDGE_HEALTH_URL="http://${bind_host}:8080/health"
  say "AI Bridge health URL resolved to $BRIDGE_HEALTH_URL"
}

scheduler_idle() {
  python3 - <<'PY'
import json, urllib.request
with urllib.request.urlopen("http://127.0.0.1:11435/status", timeout=5) as response:
    data=json.load(response)
leases=data.get("resource_leases") or {}
values=(data.get("active_count"), data.get("queued_count"), leases.get("lease_count"))
if values != (0,0,0):
    raise SystemExit(f"AI Gateway not idle: active={values[0]} queued={values[1]} leases={values[2]}")
print("PASS: AI Gateway idle (0/0/0)")
PY
}

[[ -r "$STATE_FILE" ]] || fail "rollback state missing: $STATE_FILE"
PREVIOUS="$(sed -n 's/^previous=//p' "$STATE_FILE" | head -1)"
TARGET="$(sed -n 's/^target=//p' "$STATE_FILE" | head -1)"
[[ -n "$PREVIOUS" && -d "$PREVIOUS" ]] || fail "previous release is invalid: $PREVIOUS"

resolve_bridge_health_url

if systemctl is-active --quiet ai-bridge-analysis.service; then
  fail "analysis job is currently running"
fi
scheduler_idle

if systemctl is-active --quiet "$TIMER"; then TIMER_WAS_ACTIVE=1; fi
sudo systemctl stop "$TIMER"

echo "===== ROLLBACK STAGE D RELEASE ====="
say "from=$(readlink -f "$CURRENT" 2>/dev/null || true)"
say "to=$PREVIOUS"
sudo ln -sfn "$PREVIOUS" "$CURRENT"
sudo systemctl daemon-reload
sudo systemctl restart ai-gateway.service
sudo systemctl restart ai-bridge.service

for _ in $(seq 1 30); do
  if curl -fsS --max-time 2 "$GATEWAY_HEALTH_URL" >/dev/null 2>&1      && curl -fsS --max-time 2 "$BRIDGE_HEALTH_URL" >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

curl -fsS "$GATEWAY_HEALTH_URL" >/dev/null || fail "AI Gateway health failed after rollback"
curl -fsS "$BRIDGE_HEALTH_URL" >/dev/null || fail "AI Bridge health failed after rollback"
[[ "$(readlink -f "$CURRENT")" == "$PREVIOUS" ]] || fail "rollback symlink verification failed"

scheduler_idle

if [[ "$TIMER_WAS_ACTIVE" -eq 1 ]]; then
  sudo systemctl start "$TIMER"
fi

echo "ROLLBACK STAGE D RELEASE: PASS"
say "restored=$PREVIOUS"
[[ -n "$TARGET" ]] && say "rolled_back_from=$TARGET"
