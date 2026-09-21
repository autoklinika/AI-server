#!/usr/bin/env bash
set -euo pipefail

RELEASE_ID="${1:?usage: $0 RELEASE_ID}"
ROOT="$(git rev-parse --show-toplevel)"
TARGET="/opt/ai-platform/releases/$RELEASE_ID"
CURRENT="/opt/ai-platform/current"
STATE_DIR="/var/lib/ai-platform/stage-c"
STATE_FILE="$STATE_DIR/previous-release"
TIMER="ai-bridge-analysis.timer"
SUCCESS=0
SWITCHED=0
TIMER_WAS_ACTIVE=0
PREVIOUS=""

say(){ printf '%s\n' "$*"; }
fail(){ say "FAIL: $*" >&2; exit 1; }

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

restore_previous() {
  [[ -n "$PREVIOUS" && -d "$PREVIOUS" ]] || return 0
  say "Restoring previous release: $PREVIOUS"
  sudo ln -sfn "$PREVIOUS" "$CURRENT"
  sudo systemctl restart ai-gateway.service || true
  sudo systemctl restart ai-bridge.service || true
}

cleanup() {
  rc=$?
  trap - EXIT INT TERM
  if [[ "$SUCCESS" -ne 1 ]]; then
    say "STAGE C CUTOVER FAILED"
    if [[ "$SWITCHED" -eq 1 ]]; then
      restore_previous
    fi
    if [[ "$TIMER_WAS_ACTIVE" -eq 1 ]]; then
      sudo systemctl start "$TIMER" >/dev/null 2>&1 || true
    fi
  fi
  exit "$rc"
}
trap cleanup EXIT INT TERM

[[ -d "$TARGET" ]] || fail "release missing: $TARGET"
[[ -x "$TARGET/services/ai-bridge/.venv/bin/ai-bridge" ]] || fail "AI Bridge executable missing"
[[ -x "$TARGET/services/ai-gateway/.venv/bin/python" ]] || fail "AI Gateway Python missing"
[[ -f "$TARGET/RELEASE" ]] || fail "RELEASE stamp missing"
grep -qx 'stage=C' "$TARGET/RELEASE" || fail "target is not a Stage C release"

(
  cd "$TARGET"
  sha256sum -c metadata/SHA256SUMS >/dev/null
) || fail "release checksum validation failed"
say "PASS: release checksums"

PREVIOUS="$(readlink -f "$CURRENT" 2>/dev/null || true)"
[[ -n "$PREVIOUS" && -d "$PREVIOUS" ]] || fail "current release symlink is invalid"
[[ "$PREVIOUS" != "$TARGET" ]] || fail "target release is already active"

for unit in ai-bridge.service ai-gateway.service; do
  wd="$(systemctl show "$unit" -p WorkingDirectory --value)"
  [[ "$wd" == /opt/ai-platform/current/services/* ]]     || fail "$unit is not release-managed: WorkingDirectory=$wd"
done

if systemctl is-active --quiet ai-bridge-analysis.service; then
  fail "analysis job is currently running"
fi

scheduler_idle

if systemctl is-active --quiet "$TIMER"; then
  TIMER_WAS_ACTIVE=1
fi
sudo systemctl stop "$TIMER"

sudo install -d -m 0755 "$STATE_DIR"
{
  printf 'previous=%s\n' "$PREVIOUS"
  printf 'target=%s\n' "$TARGET"
  printf 'activated_at=%s\n' "$(date -Iseconds)"
} | sudo tee "$STATE_FILE" >/dev/null
sudo chmod 0644 "$STATE_FILE"

echo "===== ACTIVATE STAGE C RELEASE ====="
sudo ln -sfn "$TARGET" "$CURRENT"
SWITCHED=1

sudo systemctl restart ai-gateway.service
sudo systemctl restart ai-bridge.service

for _ in $(seq 1 30); do
  if curl -fsS --max-time 2 http://127.0.0.1:11435/health >/dev/null 2>&1      && curl -fsS --max-time 2 http://192.168.1.55:8080/health >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

curl -fsS http://127.0.0.1:11435/health >/dev/null || fail "AI Gateway health failed"
curl -fsS http://192.168.1.55:8080/health >/dev/null || fail "AI Bridge health failed"

[[ "$(readlink -f "$CURRENT")" == "$TARGET" ]] || fail "current symlink does not point at target"
[[ "$(systemctl is-active ai-gateway.service)" == "active" ]] || fail "AI Gateway not active"
[[ "$(systemctl is-active ai-bridge.service)" == "active" ]] || fail "AI Bridge not active"

scheduler_idle

if [[ "$TIMER_WAS_ACTIVE" -eq 1 ]]; then
  sudo systemctl start "$TIMER"
fi

SUCCESS=1
trap - EXIT INT TERM

echo "===== STAGE C CUTOVER PASS ====="
say "previous=$PREVIOUS"
say "current=$(readlink -f "$CURRENT")"
say "rollback: $ROOT/deploy/stage-c/rollback_release.sh"
