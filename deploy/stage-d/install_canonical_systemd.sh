#!/usr/bin/env bash
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel)"
STATE_DIR="/var/lib/ai-platform/stage-d/systemd-baseline"
MARKER="$STATE_DIR/captured"
LEGACY_DROPIN="95-ai-platform-release.conf"
UNITS=("ai-bridge.service" "ai-gateway.service" "ai-bridge-analysis.service")

say(){ printf '%s\n' "$*"; }
fail(){ say "FAIL: $*" >&2; exit 1; }

for unit in "${UNITS[@]}"; do
  [[ -f "$ROOT/deploy/systemd/$unit" ]] || fail "canonical unit missing: $unit"
done

sudo install -d -m 0755 "$STATE_DIR"
if ! sudo test -f "$MARKER"; then
  for unit in "${UNITS[@]}"; do
    unit_path="/etc/systemd/system/$unit"
    dropin_path="/etc/systemd/system/$unit.d/$LEGACY_DROPIN"
    if sudo test -f "$unit_path"; then
      sudo cp -a "$unit_path" "$STATE_DIR/$unit"
    else
      sudo touch "$STATE_DIR/$unit.absent"
    fi
    if sudo test -f "$dropin_path"; then
      sudo cp -a "$dropin_path" "$STATE_DIR/$unit.$LEGACY_DROPIN"
    else
      sudo touch "$STATE_DIR/$unit.$LEGACY_DROPIN.absent"
    fi
  done
  printf 'captured_at=%s\n' "$(date -Iseconds)" | sudo tee "$MARKER" >/dev/null
  sudo chmod 0644 "$MARKER"
fi

for unit in "${UNITS[@]}"; do
  sudo install -m 0644 "$ROOT/deploy/systemd/$unit" "/etc/systemd/system/$unit"
  dropin="/etc/systemd/system/$unit.d/$LEGACY_DROPIN"
  if sudo test -f "$dropin"; then
    sudo rm -f "$dropin"
  fi
done

sudo systemctl daemon-reload
for unit in "${UNITS[@]}"; do
  wd="$(systemctl show "$unit" -p WorkingDirectory --value)"
  [[ "$wd" == /opt/ai-platform/current/services/* ]] || fail "$unit WorkingDirectory is not release-managed: $wd"
  if systemctl cat "$unit" | grep -q "$LEGACY_DROPIN"; then
    fail "$unit still includes legacy Stage A release-path drop-in"
  fi
done

say "CANONICAL SYSTEMD INSTALL: PASS"
say "No service was restarted; active runtime processes are unchanged."
