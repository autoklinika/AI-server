#!/usr/bin/env bash
set -euo pipefail

ENV_FILE="${AI_BRIDGE_ENV_FILE:-/etc/ai-bridge/ai-bridge.env}"
STATE_DIR="/var/lib/ai-platform/stage-d/gateway-policy-baseline"
BACKUP="$STATE_DIR/ai-bridge.env"
MARKER="$STATE_DIR/captured"

say(){ printf '%s\n' "$*"; }
fail(){ say "FAIL: $*" >&2; exit 1; }

sudo test -f "$ENV_FILE" || fail "AI Bridge env file missing: $ENV_FILE"
sudo install -d -m 0700 "$STATE_DIR"

if ! sudo test -f "$MARKER"; then
  sudo cp -a "$ENV_FILE" "$BACKUP"
  printf 'source=%s\ncaptured_at=%s\n' "$ENV_FILE" "$(date -Iseconds)" \
    | sudo tee "$MARKER" >/dev/null
  sudo chmod 0644 "$MARKER"
fi

sudo python3 - "$ENV_FILE" <<'PY'
from __future__ import annotations

import os
from pathlib import Path
import stat
import sys
import tempfile

path = Path(sys.argv[1])
metadata = path.stat()
lines = path.read_text(encoding="utf-8").splitlines()

key = "AI_BRIDGE_ANALYSIS_USE_GATEWAY"
output: list[str] = []
written = False
for line in lines:
    if line.startswith(f"{key}="):
        if not written:
            output.append(f"{key}=true")
            written = True
        continue
    output.append(line)

if not written:
    if output and output[-1] != "":
        output.append("")
    output.append(f"{key}=true")

fd, tmp_name = tempfile.mkstemp(
    dir=path.parent,
    prefix=f".{path.name}.stage-d-",
    text=True,
)
try:
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write("\n".join(output) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(tmp_name, stat.S_IMODE(metadata.st_mode))
    os.chown(tmp_name, metadata.st_uid, metadata.st_gid)
    os.replace(tmp_name, path)
finally:
    if os.path.exists(tmp_name):
        os.unlink(tmp_name)
PY

VALUE="$(sudo sed -n 's/^AI_BRIDGE_ANALYSIS_USE_GATEWAY=//p' "$ENV_FILE")"
[[ "$VALUE" == "true" ]] || fail "gateway-default policy validation failed: $VALUE"
COUNT="$(sudo grep -c '^AI_BRIDGE_ANALYSIS_USE_GATEWAY=' "$ENV_FILE")"
[[ "$COUNT" == "1" ]] || fail "expected exactly one gateway policy entry, got $COUNT"

say "GATEWAY DEFAULT POLICY: PASS"
say "AI_BRIDGE_ANALYSIS_USE_GATEWAY=true"
say "No service was restarted; backup=$BACKUP"
