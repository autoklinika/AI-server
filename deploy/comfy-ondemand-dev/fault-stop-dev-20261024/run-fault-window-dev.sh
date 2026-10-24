#!/usr/bin/env bash
# Short operator-controlled maintenance, DEV only, with independent rollback.
# No production install/disable/restart of GPU drivers, no permanent systemd edits.
set -Eeuo pipefail
umask 077
BASE=/srv/ai-data/staging/comfy-ondemand-faults-dev-20261024
HARNESS="$BASE/real_comfy_gpu_fault_harness.py"
ROLLBACK="$BASE/rollback-fault-window-dev.sh"
WATCHDOG=ai-rm-comfy-faultrestore-20261024
DEV=ai-rm-comfy-ondemand-dev.service
MODE=--check
if (( $# )); then MODE="$1"; fi
if [[ "$MODE" != "--check" && "$MODE" != "--run" ]]; then
  echo "Usage: bash run-maintenance-dev.sh --check | sudo bash run-maintenance-dev.sh --run";exit 2
fi
cd "$BASE"
exec 9>/srv/ai-data/staging/comfy-ondemand-maintenance-dev-20261023/.maintenance-global.lock
flock -n 9 || { echo "BLOCKED: concurrent GPU maintenance"; exit 12; }
test -f "$HARNESS" && test -f "$ROLLBACK"
test ! -e "$BASE/dev-residency.blocked"
test ! -e "$BASE/real-comfy-gpu-result.json"
test ! -e /srv/ai-data/staging/comfy-ondemand-maintenance-dev-20261023/dev-residency.blocked
test "$(systemctl show -P ActiveState ai-rm-comfy-restore-20261023.timer)" = inactive
# Readable and writable from the exact nonroot account BEFORE service outage.
# Root with umask 077 previously created these as root:root mode 0700.
for folder in input output temp user; do
  work="$BASE/$folder"
  if [[ -L "$work" || ! -d "$work" ]]; then
    echo "DEV_DIRECTORY_NOT_PREPARED=$work";exit 33
  fi
  if [[ "$(stat -c %U:%G:%a "$work")" != "harrypotter:harrypotter:700" ]]; then
    echo "DEV_DIRECTORY_OWNER_MODE_INVALID=$work";exit 34
  fi
  if [[ "$MODE" == "--run" ]]; then
    runuser -u harrypotter -- test -r "$work" -a -w "$work" -a -x "$work" || {
      echo "DEV_COMFY_USER_DIRECTORY_ACCESS_DENIED=$work";exit 35;
    }
  else
    test -r "$work" -a -w "$work" -a -x "$work" || {
      echo "DEV_DIRECTORY_ACCESS_CHECK_DENIED=$work";exit 36;
    }
  fi
done
echo "DEV_COMFY_UID_DIRECTORY_RW_PASS"
test "$(systemctl is-active ai-egpu-gen3-ha.service)" == active
test "$(systemctl is-active ai-gateway.service)" == active
test "$(systemctl is-active comfyui.service)" == active
test "$(systemctl is-active ollama.service)" == active
test "$(systemctl show -P MainPID ai-gateway.service)" -gt 1
test "$(systemctl show -P MainPID comfyui.service)" -gt 1
test "$(systemctl show -P MainPID ollama.service)" -gt 1
test "$(systemctl show -P ActiveState "$DEV")" == inactive
test "$(systemctl show -P MainPID "$DEV")" == 0
test "$(systemctl show -P LoadState "$DEV")" == not-found
! ss -lnt | grep -q '127.0.0.1:11657'
test "$(systemctl is-enabled comfyui.service)" == enabled
test -f /etc/systemd/system/ai-gateway.service.d/98-comfyui-ready.conf
grep -q '^Requires=comfyui.service$' /etc/systemd/system/ai-gateway.service.d/98-comfyui-ready.conf
test "$(cat /sys/bus/pci/devices/0000:c6:00.0/vendor)" == 0x1002
test "$(cat /sys/bus/pci/devices/0000:c6:00.0/device)" == 0x150e
python3 - <<'PY'
import json,subprocess
from urllib.request import urlopen
with urlopen("http://127.0.0.1:11435/health",timeout=4) as f:r=json.load(f)
assert r.get("status")=="ok"
assert r["resource_manager"]["state"]=="IDLE"
assert r["gpu_residency"]["recovery_required"] is False
assert r["scheduler"]["active_count"]==r["scheduler"]["queued_count"]==0
with urlopen("http://127.0.0.1:11434/api/ps",timeout=3) as f:
    assert json.load(f)["models"]==[]
with urlopen("http://127.0.0.1:8188/ai-platform/residency",timeout=4) as f:
    comfy=json.load(f)
assert comfy["schema_version"]==1
assert comfy["loaded_models"]==comfy["queue_running"]==comfy["queue_pending"]==0
assert comfy["cleanup_pending"] is False
with urlopen("http://127.0.0.1:8188/queue",timeout=4) as f:
    q=json.load(f)
assert q["queue_running"]==q["queue_pending"]==[]
v=subprocess.run(["nvidia-smi","--query-gpu=memory.used,pcie.link.gen.current,pcie.link.width.current",
                  "--format=csv,noheader,nounits"],capture_output=True,text=True,timeout=5,check=True)
gpu=list(map(int,v.stdout.strip().split(",")))
assert gpu[0]<=256 and gpu[1:]==[3,4]
print("MAINTENANCE_PREFLIGHT_PASS_RM_AND_PHYSICAL_GPU",flush=True)
PY
if [[ "$MODE" == "--check" ]]; then
  echo "DEV_MAINTENANCE_DRYRUN_PASS"
  echo "NOT_EXECUTED: no services or unit configurations changed"
  exit 0
fi
if [[ "$(id -u)" -ne 0 ]]; then
  echo "Operator administrator authorization required; refusing service actions";exit 3
fi
if [[ "$(systemctl is-active "$WATCHDOG.timer" 2>/dev/null || true)" == active ]]; then
  echo "Existing rollback timer detected; refuse to start";exit 4
fi

mkdir -p "$BASE/backup"
mkdir -p /run/ai-rm-comfy-fault-safety-20261024
chmod 0700 /run/ai-rm-comfy-fault-safety-20261024
install -o root -g root -m 0700 "$ROLLBACK" /run/ai-rm-comfy-fault-safety-20261024/rollback.sh
for unit in ai-gateway.service comfyui.service ollama.service; do
  systemctl cat "$unit" > "$BASE/backup/$unit.effective" 2>&1
  systemctl show "$unit" --property=FragmentPath,DropInPaths,Requires,After,ExecStart,Restart,UnitFileState \
    > "$BASE/backup/$unit.properties"
done
sha256sum "$HARNESS" "$ROLLBACK" > "$BASE/backup/runner-hashes.txt"
date -Is > "$BASE/backup/preflight-at.txt"
echo "ROLLBACK_WATCHDOG_ARMING"
# Independent system-manager timer survives a terminal or SSH disconnect.
systemd-run --system --on-active=12min --unit="$WATCHDOG" \
  /usr/bin/bash /run/ai-rm-comfy-fault-safety-20261024/rollback.sh >"$BASE/watchdog-setup.log" 2>&1
test "$(systemctl is-active "$WATCHDOG.timer")" == active
echo "ROLLBACK_WATCHDOG_ARMED"
needs_rollback=0
cleanup() {
  local status=$?
  trap - EXIT INT TERM
  if (( needs_rollback == 1 )); then
    echo "PRODUCTION_RESTORE_BEGIN"
    if timeout 400 /usr/bin/bash /run/ai-rm-comfy-fault-safety-20261024/rollback.sh; then
      echo "PRODUCTION_RESTORE_PASS"
      systemctl stop "$WATCHDOG.timer" >/dev/null 2>&1 || true
    else
      echo "PRODUCTION_RESTORE_NOT_VERIFIED: independent watchdog remains armed"
      status=90
    fi
  else
    systemctl stop "$WATCHDOG.timer" >/dev/null 2>&1 || true
  fi
  echo "MAINTENANCE_EXIT_CODE=$status"
  exit "$status"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

echo "BEGIN_TEMPORARY_MAINTENANCE"
needs_rollback=1
timeout 30 systemctl stop ai-gateway.service
timeout 40 systemctl stop comfyui.service
test "$(systemctl show -P MainPID comfyui.service)" == 0
test "$(systemctl show -P MainPID ai-gateway.service)" == 0
test "$(systemctl is-active comfyui.service)" == inactive
test "$(systemctl is-active ai-gateway.service)" == inactive
! ss -lnt | grep -q '127.0.0.1:8188'
! ss -lnt | grep -q '127.0.0.1:11435'
# Prevent a second AMD owner from contaminating the GPU acceptance.
set +e
owners="$(fuser /dev/kfd /dev/dri/renderD128 2>"$BASE/owners-after-stop.log")"
owners_rc=$?
set -e
if (( owners_rc != 1 )) || [[ -n "$owners" ]]; then
  echo "GPU_OWNERSHIP_NOT_EXCLUSIVE: refusing DEV start"
  exit 18
fi
echo "GPU_OWNER_FREE_WINDOW_PASS"
echo "REAL_GPU_DEV_START"
PYTHONPATH=/srv/ai-data/staging/gpu-dual-route-20261023/AI-server-dev/src \
 timeout --signal=TERM --kill-after=15s 240s \
 /home/harrypotter/AI-server/.venv/bin/python -u -B "$HARNESS" \
  > "$BASE/real-gpu-dev.log" 2>&1 || {
    tail -20 "$BASE/real-gpu-dev.log"
    echo "DEV_GPU_TEST_FAIL_CLOSED"
    exit 19
  }
grep -q '^DEV_EXPECTED_STOP_FAULT_RM_FENCED_PASS$' "$BASE/real-gpu-dev.log"
echo "DEV_EXPECTED_STOP_FAILURE_PENDING_ROLLBACK"
