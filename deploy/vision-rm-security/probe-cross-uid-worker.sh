#!/usr/bin/env bash
# Read-only cross-UID /proc evidence test; starts ONLY temporary CPU sleep.
set -euo pipefail
if [[ "${1:-}" != "--verify" || ${#} -ne 1 || $EUID -ne 0 ]]; then
  echo "Usage: sudo bash probe-cross-uid-worker.sh --verify" >&2
  exit 2
fi
getent passwd ai-vision >/dev/null
getent passwd ai-gateway-rm >/dev/null
TMP="$(mktemp)"
CHILD=""
cleanup() {
  if [[ -n "${PID:-}" && "$PID" =~ ^[1-9][0-9]{1,9}$ ]]; then
    kill "$PID" 2>/dev/null || true
  fi
  if [[ -n "$CHILD" ]]; then
    kill "$CHILD" 2>/dev/null || true
    wait "$CHILD" 2>/dev/null || true
  fi
  rm -f -- "$TMP"
}
trap cleanup EXIT
runuser -u ai-vision -- /usr/bin/python3 -c 'import os,time;print(os.getpid(),flush=True);time.sleep(12)' > "$TMP" &
CHILD=$!
for i in {1..40}; do
  [[ -s "$TMP" ]] && break
  sleep 0.05
done
PID="$(head -1 "$TMP")"
if [[ ! "$PID" =~ ^[1-9][0-9]{1,9}$ ]]; then
  echo "MODEL_PROCESS_NOT_STARTED" >&2
  exit 3
fi
echo "WORKER_PROBE_PID=$PID"
runuser -u ai-gateway-rm -- /usr/bin/python3 - "$PID" <<'PYPROBE'
from pathlib import Path
import sys
pid=int(sys.argv[1])
root=Path(f"/proc/{pid}")
try:
    owner=root.stat().st_uid
    print("MODEL_PROC_OWNER_UID="+str(owner))
except OSError as e:
    print("MODEL_PROC_OWNER_READ=FAIL errno="+str(e.errno))
for name in ("stat","cgroup","cmdline"):
    try:
        data=(root/name).read_bytes()
        print("CROSS_UID_"+name.upper()+"="+("PASS" if data else "EMPTY"))
    except OSError as e:
        print("CROSS_UID_"+name.upper()+"=DENIED errno="+str(e.errno))
try:
    exe=(root/"exe").resolve(strict=True)
    print("CROSS_UID_EXE_LINK=PASS")
except OSError as e:
    print("CROSS_UID_EXE_LINK=DENIED errno="+str(e.errno))
PYPROBE
echo "READ_ONLY_PROCESS_EVIDENCE_TEST=COMPLETE"
