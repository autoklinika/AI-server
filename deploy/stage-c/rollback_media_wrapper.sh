#!/usr/bin/env bash
set -euo pipefail

WRAPPER="/usr/local/bin/generate-video-ltx23"
BACKUP="/srv/ai-data/platform/recovery/stage-c-provider-abstraction/media-wrapper/generate-video-ltx23.pre-stage-c"

say(){ printf '%s\n' "$*"; }
fail(){ say "FAIL: $*" >&2; exit 1; }

python3 - <<'PY'
import json, urllib.request
with urllib.request.urlopen("http://127.0.0.1:11435/status", timeout=5) as r:
    status=json.load(r)
leases=status.get("resource_leases") or {}
counts=(status.get("active_count"), status.get("queued_count"), leases.get("lease_count"))
if counts != (0,0,0):
    raise SystemExit(f"AI Gateway not idle: active={counts[0]} queued={counts[1]} leases={counts[2]}")
with urllib.request.urlopen("http://127.0.0.1:8188/queue", timeout=5) as r:
    queue=json.load(r)
if (queue.get("queue_running") or []) or (queue.get("queue_pending") or []):
    raise SystemExit("ComfyUI queue is not idle")
print("PASS: media runtime idle")
PY

sudo test -e "$BACKUP" || fail "media wrapper backup missing: $BACKUP"

echo "===== RESTORE PRE-STAGE-C MEDIA WRAPPER ====="
sudo cp -a "$BACKUP" "$WRAPPER"
[[ -x "$WRAPPER" ]] || fail "restored wrapper is not executable"

if grep -q 'STAGE_C_PROVIDER_MEDIA_WRAPPER=1' "$WRAPPER" 2>/dev/null; then
  fail "rollback restored the Stage C wrapper instead of the previous wrapper"
fi

"$WRAPPER" --preflight >/dev/null || fail "restored wrapper preflight failed"

echo "ROLLBACK MEDIA WRAPPER: PASS"
say "restored=$WRAPPER"
