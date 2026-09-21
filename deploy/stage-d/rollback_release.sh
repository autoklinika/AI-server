#!/usr/bin/env bash
set -euo pipefail

CURRENT="/opt/ai-platform/current"
RELEASES="/opt/ai-platform/releases"
STATE_FILE="/var/lib/ai-platform/stage-d/previous-release"
EXPLICIT_RELEASE_ID="${1:-}"
TIMER="ai-bridge-analysis.timer"
BRIDGE_HEALTH_URL="${AI_BRIDGE_HEALTH_URL:-}"
GATEWAY_HEALTH_URL="${AI_GATEWAY_HEALTH_URL:-http://127.0.0.1:11435/health}"
TIMER_WAS_ACTIVE=0
SUCCESS=0
SWITCHED=0
SOURCE_RELEASE=""
ROLLBACK_RELEASE=""
ROLLBACK_MODE=""

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
    raise SystemExit(
        f"AI Gateway not idle: active={values[0]} "
        f"queued={values[1]} leases={values[2]}"
    )
print("PASS: AI Gateway idle (0/0/0)")
PY
}

restore_source_after_failure() {
  [[ -n "$SOURCE_RELEASE" && -d "$SOURCE_RELEASE" ]] || return 0
  say "Restoring source release after failed rollback: $SOURCE_RELEASE"
  sudo ln -sfn "$SOURCE_RELEASE" "$CURRENT"
  sudo systemctl daemon-reload || true
  sudo systemctl restart ai-gateway.service || true
  sudo systemctl restart ai-bridge.service || true
}

cleanup() {
  rc=$?
  trap - EXIT INT TERM
  if [[ "$SUCCESS" -ne 1 ]]; then
    say "STAGE D ROLLBACK FAILED"
    if [[ "$SWITCHED" -eq 1 ]]; then
      restore_source_after_failure
    fi
    if [[ "$TIMER_WAS_ACTIVE" -eq 1 ]]; then
      sudo systemctl start "$TIMER" >/dev/null 2>&1 || true
    fi
  fi
  exit "$rc"
}
trap cleanup EXIT INT TERM

SOURCE_RELEASE="$(readlink -f "$CURRENT" 2>/dev/null || true)"
[[ -n "$SOURCE_RELEASE" && -d "$SOURCE_RELEASE" ]] \
  || fail "current release symlink is invalid"

if [[ -n "$EXPLICIT_RELEASE_ID" ]]; then
  [[ "$EXPLICIT_RELEASE_ID" != */* ]] \
    || fail "explicit release must be a release id, not a path"
  ROLLBACK_RELEASE="$RELEASES/$EXPLICIT_RELEASE_ID"
  ROLLBACK_MODE="explicit"
else
  [[ -r "$STATE_FILE" ]] || fail "rollback state missing: $STATE_FILE"
  ROLLBACK_RELEASE="$(sed -n 's/^previous=//p' "$STATE_FILE" | head -1)"
  ROLLBACK_MODE="previous"
fi

[[ -n "$ROLLBACK_RELEASE" && -d "$ROLLBACK_RELEASE" ]] \
  || fail "rollback release is invalid: $ROLLBACK_RELEASE"
[[ "$SOURCE_RELEASE" != "$ROLLBACK_RELEASE" ]] \
  || fail "rollback target is already active"
[[ -f "$ROLLBACK_RELEASE/RELEASE" ]] \
  || fail "rollback RELEASE stamp missing: $ROLLBACK_RELEASE/RELEASE"
grep -Eq '^stage=(C|D)$' "$ROLLBACK_RELEASE/RELEASE" \
  || fail "rollback release is not Stage C/D"
[[ -x "$ROLLBACK_RELEASE/services/ai-bridge/.venv/bin/ai-bridge" ]] \
  || fail "rollback AI Bridge executable missing"
[[ -x "$ROLLBACK_RELEASE/services/ai-gateway/.venv/bin/python" ]] \
  || fail "rollback AI Gateway Python missing"

if [[ -f "$ROLLBACK_RELEASE/metadata/SHA256SUMS" ]]; then
  (
    cd "$ROLLBACK_RELEASE"
    sha256sum -c metadata/SHA256SUMS >/dev/null
  ) || fail "rollback release checksum validation failed"
  say "PASS: rollback release checksums"
fi

for unit in ai-bridge.service ai-gateway.service ai-bridge-analysis.service; do
  wd="$(systemctl show "$unit" -p WorkingDirectory --value)"
  [[ "$wd" == /opt/ai-platform/current/services/* ]] \
    || fail "$unit is not release-managed: WorkingDirectory=$wd"
done

resolve_bridge_health_url

if systemctl is-active --quiet ai-bridge-analysis.service; then
  fail "analysis job is currently running"
fi
scheduler_idle

if systemctl is-active --quiet "$TIMER"; then
  TIMER_WAS_ACTIVE=1
fi
sudo systemctl stop "$TIMER"

echo "===== ROLLBACK STAGE D RELEASE ====="
say "mode=$ROLLBACK_MODE"
say "from=$SOURCE_RELEASE"
say "to=$ROLLBACK_RELEASE"

sudo ln -sfn "$ROLLBACK_RELEASE" "$CURRENT"
SWITCHED=1
sudo systemctl daemon-reload
sudo systemctl restart ai-gateway.service
sudo systemctl restart ai-bridge.service

for _ in $(seq 1 30); do
  if curl -fsS --max-time 2 "$GATEWAY_HEALTH_URL" >/dev/null 2>&1 \
      && curl -fsS --max-time 2 "$BRIDGE_HEALTH_URL" >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

curl -fsS "$GATEWAY_HEALTH_URL" >/dev/null \
  || fail "AI Gateway health failed after rollback"
curl -fsS "$BRIDGE_HEALTH_URL" >/dev/null \
  || fail "AI Bridge health failed after rollback"
[[ "$(readlink -f "$CURRENT")" == "$ROLLBACK_RELEASE" ]] \
  || fail "rollback symlink verification failed"

scheduler_idle

if [[ "$TIMER_WAS_ACTIVE" -eq 1 ]]; then
  sudo systemctl start "$TIMER"
fi

SUCCESS=1
trap - EXIT INT TERM

echo "ROLLBACK STAGE D RELEASE: PASS"
say "restored=$ROLLBACK_RELEASE"
say "rolled_back_from=$SOURCE_RELEASE"
[[ "$ROLLBACK_MODE" == "explicit" ]] \
  && say "explicit_release_id=$EXPLICIT_RELEASE_ID"
