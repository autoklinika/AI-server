#!/usr/bin/env bash
# One administrative action to update ONLY the read-only observer service.
# Gate: production GPU idle; private rollback; real cross-UID security E2E.
set -euo pipefail
if [[ "${1:-}" != "--apply" || $# -ne 1 ]]; then
  echo "Usage: sudo bash upgrade-observer-worker-exe.sh --apply";exit 2
fi
if (( EUID != 0 )); then
  echo "Administrative approval required. No privilege escalation." >&2;exit 3
fi
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
SOURCE="$ROOT/vision_gpu_observer.py"
TEST="$ROOT/test-observer-worker-exe.py"
DEST=/usr/local/libexec/ai-platform/vision-gpu-observer.py
UNIT=ai-vision-gpu-observer.service
for path in "$SOURCE" "$TEST" "$DEST"; do
  test -f "$path" && test ! -L "$path" || { echo "MISSING_OR_LINK=$path" >&2;exit 4; }
done
bash -n "$ROOT/upgrade-observer-worker-exe.sh"
python3 -m py_compile "$SOURCE" "$TEST"
systemctl is-active --quiet ai-gateway
systemctl is-active --quiet ollama
systemctl is-active --quiet "$UNIT"
python3 - <<'PYIDLE'
import json,urllib.request
with urllib.request.urlopen('http://127.0.0.1:11435/status',timeout=5) as response:
    state=json.load(response)
assert state['gpu_residency']['state']=='llm'
assert state['gpu_residency']['recovery_required'] is False
assert state['resource_leases']['lease_count']==0
assert not state['active'] and not state['queued']
print('PRODUCTION_GPU_IDLE_PREFLIGHT=PASS')
PYIDLE
test "$(stat -c %U:%G:%a "$DEST")" = root:root:755

# Keep the previous known-good service executable for recovery.
install -d -o root -g root -m 0700 /var/lib/ai-vision-gpu-observer-upgrades
BACKUP="$(mktemp /var/lib/ai-vision-gpu-observer-upgrades/observer.XXXXXXXX.bak)"
install -o root -g root -m 0600 "$DEST" "$BACKUP"
NEXT="$(mktemp /usr/local/libexec/ai-platform/.vision-observer.XXXXXXXX)"
install -o root -g root -m 0755 "$SOURCE" "$NEXT"
mv -f -- "$NEXT" "$DEST"
echo "OBSERVER_CODE_UPDATED=YES"
echo "OBSERVER_RESTART_ONLY=BEGIN"
if systemctl restart "$UNIT" && systemctl is-active --quiet "$UNIT" &&
   /usr/bin/python3 -I "$TEST"; then
  echo "OBSERVER_REAL_CROSS_UID_VERIFICATION=PASS"
  echo "PRODUCTION_GATEWAY=UNCHANGED"
  exit 0
fi
echo "OBSERVER_VERIFICATION=FAIL_RESTORING_PREVIOUS_BINARY" >&2
install -o root -g root -m 0755 "$BACKUP" "$DEST"
systemctl restart "$UNIT" || true
echo "OBSERVER_ROLLBACK_DONE=YES"
exit 5
