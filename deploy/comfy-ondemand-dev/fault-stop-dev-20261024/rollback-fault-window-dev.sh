#!/usr/bin/env bash
# One-shot operator-authorized safety rollback; invoked from maintenance trap
# or an independent transient systemd timer. No permanent unit changes.
set -Eeuo pipefail
umask 077
BASE=/srv/ai-data/staging/comfy-ondemand-faults-dev-20261024
DEV=ai-rm-comfy-ondemand-dev.service
mkdir -p "$BASE"
exec >>"$BASE/rollback.log" 2>&1
echo "ROLLBACK_BEGIN $(date -Is)"
if [[ "$(id -u)" -ne 0 ]]; then echo "ROLLBACK_REFUSE_NOT_ROOT";exit 90;fi
# Only the exact one-off test unit may be stopped.
if [[ "$(systemctl is-active "$DEV" 2>/dev/null || true)" == active ]]; then
  timeout 40 systemctl stop "$DEV" || { echo "ROLLBACK_BLOCKED_DEV_STOP";exit 91; }
fi
mainpid="$(systemctl show -P MainPID "$DEV" 2>/dev/null || true)"
if [[ -n "$mainpid" && "$mainpid" != 0 ]]; then
  echo "ROLLBACK_BLOCKED_DEV_MAINPID=$mainpid";exit 92
fi
cg="/sys/fs/cgroup/system.slice/$DEV"
if [[ -f "$cg/cgroup.procs" && -s "$cg/cgroup.procs" ]]; then
  echo "ROLLBACK_BLOCKED_TEST_CGROUP_NONEMPTY";exit 93
fi
# Do not start production while the temporary test HTTP port is still open.
if ss -lnt | grep -q '127.0.0.1:11657'; then
  echo "ROLLBACK_BLOCKED_TEST_PORT_STILL_OPEN";exit 94
fi
# Restore only two services that were deliberately interrupted.
timeout 175 systemctl start comfyui.service || { echo "ROLLBACK_FAILED_COMFY_START";exit 95; }
timeout 100 systemctl start ai-gateway.service || { echo "ROLLBACK_FAILED_GATEWAY_START";exit 96; }
python3 - <<'PY'
import json,time
from urllib.request import urlopen
deadline=time.monotonic()+90
while time.monotonic()<deadline:
    try:
        with urlopen("http://127.0.0.1:8188/ai-platform/residency",timeout=3) as x:
            r=json.load(x)
        with urlopen("http://127.0.0.1:11435/health",timeout=3) as x:
            h=json.load(x)
        if (r.get("schema_version")==1 and r.get("queue_running")==0 and
            r.get("queue_pending")==0 and r.get("loaded_models")==0 and
            r.get("cleanup_pending") is False and
            h.get("status")=="ok" and
            h["gpu_residency"]["recovery_required"] is False and
            h["scheduler"]["active_count"]==0):
            print("ROLLBACK_PRODUCTION_HTTP_SMOKE_PASS",flush=True)
            break
    except (OSError,ValueError,KeyError,TypeError):
        pass
    time.sleep(.75)
else:
    raise SystemExit("ROLLBACK_HTTP_HEALTH_NOT_VERIFIED")
PY
echo "ROLLBACK_COMPLETE $(date -Is)"
