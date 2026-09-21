#!/usr/bin/env bash
set -euo pipefail

STATE_DIR="/var/lib/ai-platform/stage-d/systemd-baseline"
MARKER="$STATE_DIR/captured"
LEGACY_DROPIN="95-ai-platform-release.conf"
UNITS=("ai-bridge.service" "ai-gateway.service" "ai-bridge-analysis.service")

say(){ printf '%s\n' "$*"; }
fail(){ say "FAIL: $*" >&2; exit 1; }

sudo test -f "$MARKER" || fail "systemd baseline was not captured"

for unit in "${UNITS[@]}"; do
  unit_path="/etc/systemd/system/$unit"
  if sudo test -f "$STATE_DIR/$unit.absent"; then
    sudo rm -f "$unit_path"
  else
    sudo install -m 0644 "$STATE_DIR/$unit" "$unit_path"
  fi

  dropin_dir="/etc/systemd/system/$unit.d"
  dropin_path="$dropin_dir/$LEGACY_DROPIN"
  if sudo test -f "$STATE_DIR/$unit.$LEGACY_DROPIN.absent"; then
    sudo rm -f "$dropin_path"
  else
    sudo install -d -m 0755 "$dropin_dir"
    sudo install -m 0644 "$STATE_DIR/$unit.$LEGACY_DROPIN" "$dropin_path"
  fi
done

sudo systemctl daemon-reload
say "SYSTEMD COMPATIBILITY RESTORE: PASS"
say "No service was restarted; restart/cutover remains an explicit operator action."
