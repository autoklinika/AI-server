#!/usr/bin/env bash
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel)"
CURRENT="/opt/ai-platform/current"
SERVICE_ROOT="$CURRENT/services/ai-bridge"
PYTHON="$SERVICE_ROOT/.venv/bin/python"
GENERATOR="$SERVICE_ROOT/tools/local_video/generate_ltx23_stage30.py"
WRAPPER="/usr/local/bin/generate-video-ltx23"
BACKUP_DIR="/srv/ai-data/platform/recovery/stage-c-provider-abstraction/media-wrapper"
BACKUP="$BACKUP_DIR/generate-video-ltx23.pre-stage-c"
SUCCESS=0
MUTATED=0

say(){ printf '%s\n' "$*"; }
fail(){ say "FAIL: $*" >&2; exit 1; }

idle_check() {
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
running=queue.get("queue_running") or []
pending=queue.get("queue_pending") or []
if running or pending:
    raise SystemExit(f"ComfyUI queue not idle: running={len(running)} pending={len(pending)}")

print("PASS: AI Gateway 0/0/0 and ComfyUI queue empty")
PY
}

restore_backup() {
  if sudo test -e "$BACKUP"; then
    sudo cp -a "$BACKUP" "$WRAPPER"
  fi
}

cleanup() {
  rc=$?
  trap - EXIT INT TERM
  if [[ "$SUCCESS" -ne 1 && "$MUTATED" -eq 1 ]]; then
    say "MEDIA WRAPPER CUTOVER FAILED — restoring previous wrapper"
    restore_backup || true
  fi
  exit "$rc"
}
trap cleanup EXIT INT TERM

[[ -x "$PYTHON" ]] || fail "active release Python missing: $PYTHON"
[[ -r "$GENERATOR" ]] || fail "Stage30 generator missing in active release: $GENERATOR"
grep -qx 'stage=C' "$CURRENT/RELEASE" || fail "active release is not Stage C"
[[ -x "$WRAPPER" ]] || fail "current video wrapper missing: $WRAPPER"

idle_check

echo "===== PRE-CUTOVER RELEASE PREFLIGHTS ====="
"$PYTHON" "$GENERATOR" --preflight >/dev/null
"$PYTHON" "$GENERATOR" --i2v-preflight --upscale-2x >/dev/null
say "PASS: Stage C generator read-only preflights"

sudo install -d -m 0700 "$BACKUP_DIR"
if ! sudo test -e "$BACKUP"; then
  sudo cp -a "$WRAPPER" "$BACKUP"
  say "PASS: previous wrapper backed up"
else
  say "PASS: existing Stage C wrapper backup retained"
fi

TMP="$(mktemp)"
trap 'rm -f "$TMP"' RETURN
cat > "$TMP" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
# STAGE_C_PROVIDER_MEDIA_WRAPPER=1
ROOT="/opt/ai-platform/current/services/ai-bridge"
PYTHON="$ROOT/.venv/bin/python"
GENERATOR="$ROOT/tools/local_video/generate_ltx23_stage30.py"
[[ -x "$PYTHON" ]] || { echo "ERROR: active AI Platform Python missing: $PYTHON" >&2; exit 1; }
[[ -r "$GENERATOR" ]] || { echo "ERROR: active Stage30 generator missing: $GENERATOR" >&2; exit 1; }
exec "$PYTHON" "$GENERATOR" "$@"
EOF

MUTATED=1
sudo install -m 0755 "$TMP" "$WRAPPER"
rm -f "$TMP"

grep -q 'STAGE_C_PROVIDER_MEDIA_WRAPPER=1' "$WRAPPER"   || fail "installed wrapper marker missing"

echo "===== POST-CUTOVER WRAPPER PREFLIGHTS ====="
"$WRAPPER" --preflight >/dev/null
"$WRAPPER" --i2v-preflight --upscale-2x >/dev/null
idle_check

SUCCESS=1
MUTATED=0
trap - EXIT INT TERM

echo "MEDIA WRAPPER CUTOVER: PASS"
say "wrapper=$WRAPPER"
say "generator=$GENERATOR"
say "rollback=$ROOT/deploy/stage-c/rollback_media_wrapper.sh"
