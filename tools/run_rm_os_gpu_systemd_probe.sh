#!/usr/bin/env bash
# GPU cgroup negative/positive test. Execute as the ordinary user.
# Only systemd-run calls use sudo. This script itself does not run as root.
set -euo pipefail
attempt="os-gpu-gate-$(date -u +%Y%m%d-%H%M%S)-$$"
folder="/srv/ai-data/evaluation/$attempt"
if [[ "$(id -u)" -eq 0 ]]; then
  echo 'FAIL: ordinary user required' >&2
  exit 2
fi
for service in ai-bridge-analysis.timer ai-gateway.service ai-bridge.service ollama.service comfyui.service; do
  if [[ "$(systemctl is-active "$service" 2>/dev/null || true)" != inactive ]]; then
    echo "FAIL: service not stopped: $service" >&2
    exit 2
  fi
done
if [[ -n "$(ls -A /sys/class/kfd/kfd/proc)" ]]; then
  echo 'FAIL: KFD process still exists' >&2
  exit 2
fi
mkdir -m 700 "$folder"
echo "OBSERVATION_DIR=$folder"

deny_code='import os,errno,sys
print("IDENTITY",os.geteuid(),open("/proc/self/cgroup").read().strip(),flush=True)
if os.geteuid()!=994: sys.exit(6)
for path in ("/dev/kfd","/dev/dri/renderD128"):
 try:
  fd=os.open(path,os.O_RDONLY|os.O_CLOEXEC)
 except OSError as exc:
  if exc.errno not in (errno.EACCES,errno.EPERM): sys.exit(5)
  print("DENIED_AS_REQUIRED",path,flush=True)
 else:
  os.close(fd)
  print("UNSAFE_OPEN",path,flush=True)
  sys.exit(4)'
allow_code='import os,sys
print("IDENTITY",os.geteuid(),open("/proc/self/cgroup").read().strip(),flush=True)
if os.geteuid()!=994: sys.exit(6)
for path in ("/dev/kfd","/dev/dri/renderD128"):
 fd=os.open(path,os.O_RDONLY|os.O_CLOEXEC)
 os.close(fd)
 print("ALLOWED_AS_REQUIRED",path,flush=True)'

echo 'STAGE 1: SYSTEM DEVICE DENY'
if /usr/bin/sudo /usr/bin/systemd-run --system --wait --collect --pipe \
  --unit="ai-rm-os-deny-$$" \
  -p User=ai-vision -p Group=ai-vision-rm \
  -p NoNewPrivileges=yes -p CapabilityBoundingSet= \
  -p DevicePolicy=strict -p PrivateDevices=no \
  /usr/bin/python3 -I -S -c "$deny_code" > "$folder/deny.log" 2>&1; then
  cat "$folder/deny.log"
else
  cat "$folder/deny.log"
  echo 'FAIL: negative test' >&2
  exit 2
fi
for path in /dev/kfd /dev/dri/renderD128; do
  if ! grep -Fq "DENIED_AS_REQUIRED $path" "$folder/deny.log"; then
    echo "FAIL: deny evidence missing $path" >&2
    exit 2
  fi
done
if grep -Fq 'UNSAFE_OPEN' "$folder/deny.log"; then
  echo 'FAIL: bypass' >&2
  exit 2
fi

echo 'STAGE 2: EXACT DEVICE ALLOWLIST'
if /usr/bin/sudo /usr/bin/systemd-run --system --wait --collect --pipe \
  --unit="ai-rm-os-allow-$$" \
  -p User=ai-vision -p Group=ai-vision-rm \
  -p NoNewPrivileges=yes -p CapabilityBoundingSet= \
  -p DevicePolicy=strict -p PrivateDevices=no \
  -p 'DeviceAllow=/dev/kfd rw' -p 'DeviceAllow=/dev/dri/renderD128 rw' \
  /usr/bin/python3 -I -S -c "$allow_code" > "$folder/allow.log" 2>&1; then
  cat "$folder/allow.log"
else
  cat "$folder/allow.log"
  echo 'FAIL: positive test' >&2
  exit 2
fi
for path in /dev/kfd /dev/dri/renderD128; do
  if ! grep -Fq "ALLOWED_AS_REQUIRED $path" "$folder/allow.log"; then
    echo "FAIL: allow evidence missing $path" >&2
    exit 2
  fi
done
echo 'SYSTEM_MANAGER_DEVICE_CGROUP_NEGATIVE=PASS'
echo 'SYSTEM_MANAGER_EXACT_ALLOWLIST=PASS'
echo 'STAGE 3: BOUNDED READ-ONLY KFD POSTFLIGHT'
# Kernel KFD process teardown can finish after systemd reports unit exit.
# Observe only: do not reset GPU, delete entries or reinterpret this as E_safe.
stable=0
for sample in {1..40}; do
  if ! kfd_pids="$(find /sys/class/kfd/kfd/proc -mindepth 1 -maxdepth 1 -printf '%f ' 2>&1)"; then
    printf 'KFD_READ_ERROR sample=%s details=%s\n' "$sample" "$kfd_pids" | tee -a "$folder/kfd-postflight.log"
    echo 'KFD_POSTFLIGHT=UNVERIFIED' >&2
    exit 2
  fi
  printf 'KFD_SNAPSHOT sample=%s pids=%s\n' "$sample" "${kfd_pids:-none}" | tee -a "$folder/kfd-postflight.log"
  if [[ -z "$kfd_pids" ]]; then
    stable=$((stable + 1))
  else
    stable=0
    for pid in $kfd_pids; do
      if [[ "$pid" =~ ^[0-9]+$ ]]; then
        ps -p "$pid" -o pid=,ppid=,uid=,stat=,comm= 2>&1 | tee -a "$folder/kfd-postflight.log" || true
      fi
    done
  fi
  if (( stable >= 3 )); then
    break
  fi
  sleep 0.25
done
if (( stable < 3 )); then
  echo 'KFD_POSTFLIGHT=UNVERIFIED: contexts remained visible past bounded window' >&2
  echo 'GLOBAL_OS_EXCLUSIVITY=NOT_VERIFIED'
  echo 'GPU_REUSE_SAFE=NOT_VERIFIED'
  echo "LOGS=$folder"
  exit 2
fi
echo 'KFD_POSTFLIGHT=THREE_CONSECUTIVE_EMPTY_OBSERVATIONS'
echo 'GLOBAL_OS_EXCLUSIVITY=NOT_VERIFIED'
echo 'GPU_REUSE_SAFE=NOT_VERIFIED'
echo "LOGS=$folder"
