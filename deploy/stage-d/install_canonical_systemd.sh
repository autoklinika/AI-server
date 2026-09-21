#!/usr/bin/env bash
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel)"
STATE_DIR="/var/lib/ai-platform/stage-d/systemd-baseline"
MARKER="$STATE_DIR/captured"
LEGACY_DROPIN="95-ai-platform-release.conf"
OBSOLETE_DROPINS=(
  "ai-bridge.service.d/90-production-source.conf"
  "ai-bridge-analysis.service.d/10-ai-gateway.conf"
  "ai-bridge-analysis.service.d/90-production-source.conf"
)
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

# D.0 may discover additional historical drop-ins after the original baseline
# was captured. Capture each one exactly once before removal so cleanup remains
# reversible even when STATE_DIR/captured already exists.
for rel in "${OBSOLETE_DROPINS[@]}"; do
  src="/etc/systemd/system/$rel"
  safe_name="${rel//\//__}"
  if ! sudo test -e "$STATE_DIR/$safe_name" \
      && ! sudo test -e "$STATE_DIR/$safe_name.absent"; then
    if sudo test -f "$src"; then
      sudo cp -a "$src" "$STATE_DIR/$safe_name"
    else
      sudo touch "$STATE_DIR/$safe_name.absent"
    fi
  fi
done

for unit in "${UNITS[@]}"; do
  sudo install -m 0644 "$ROOT/deploy/systemd/$unit" "/etc/systemd/system/$unit"
  dropin="/etc/systemd/system/$unit.d/$LEGACY_DROPIN"
  if sudo test -f "$dropin"; then
    sudo rm -f "$dropin"
  fi
done

for rel in "${OBSOLETE_DROPINS[@]}"; do
  path="/etc/systemd/system/$rel"
  if sudo test -f "$path"; then
    sudo rm -f "$path"
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

for stale in \
  '/opt/ai-bridge/src' \
  '/opt/ai-bridge/.venv/bin/ai-bridge-analyze-ventilation' \
  'AI_BRIDGE_OLLAMA_URL=http://127.0.0.1:11435/clients/ventilation'
do
  if systemctl cat ai-bridge.service ai-bridge-analysis.service | grep -Fq "$stale"; then
    fail "obsolete systemd override still effective: $stale"
  fi
done

say "CANONICAL SYSTEMD INSTALL: PASS"
say "No service was restarted; active runtime processes are unchanged."
