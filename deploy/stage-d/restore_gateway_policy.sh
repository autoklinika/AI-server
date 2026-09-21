#!/usr/bin/env bash
set -euo pipefail

ENV_FILE="${AI_BRIDGE_ENV_FILE:-/etc/ai-bridge/ai-bridge.env}"
STATE_DIR="/var/lib/ai-platform/stage-d/gateway-policy-baseline"
BACKUP="$STATE_DIR/ai-bridge.env"
MARKER="$STATE_DIR/captured"

say(){ printf '%s\n' "$*"; }
fail(){ say "FAIL: $*" >&2; exit 1; }

sudo test -f "$MARKER" || fail "gateway policy baseline was not captured"
sudo test -f "$BACKUP" || fail "gateway policy backup missing: $BACKUP"

sudo cp -a "$BACKUP" "$ENV_FILE"

say "GATEWAY POLICY RESTORE: PASS"
say "restored=$ENV_FILE"
say "No service was restarted; restart/cutover remains an explicit operator action."
