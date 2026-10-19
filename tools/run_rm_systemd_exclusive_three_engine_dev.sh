#!/usr/bin/env bash
# GPU RM EXCLUSIVE systemd integration pilot, one operator invocation.
# No persistent systemd changes, no driver reset, and NO N1 GPU grant.
set -Eeuo pipefail
umask 077
BASE=/srv/ai-data/evaluation/rm-exclusive-handoff-dev-20261019
cd "$BASE"
if [[ "$(id -u)" -eq 0 ]]; then echo "FAIL: run as ordinary operator" >&2; exit 2; fi

for service in gdm.service ai-gateway.service ai-bridge.service ollama.service comfyui.service ai-bridge-analysis.timer; do
  if [[ "$(systemctl is-active "$service" 2>/dev/null || true)" != "inactive" ]]; then
    echo "BLOCKED: active or unknown service $service" >&2; exit 2
  fi
done
if [[ "$(cat /sys/bus/pci/devices/0000:c6:00.0/vendor)" != 0x1002 ||
      "$(cat /sys/bus/pci/devices/0000:c6:00.0/device)" != 0x150e ]]; then
  echo "BLOCKED: PCI identity mismatch" >&2; exit 2
fi
mkdir -p "$BASE/systemd-pilot"
exec 9>"$BASE/systemd-pilot/.global-lock"
flock -n 9 || { echo "BLOCKED: another RM systemd pilot owns the lock" >&2; exit 2; }
folder=$(mktemp -d "$BASE/systemd-pilot/attempt-$(date -u +%Y%m%d-%H%M%S)-XXXXXXXX")
printf 'ATTEMPT_DIR=%s\n' "$folder"
id="p$(date -u +%H%M%S)-$$"
current=""
completed=0
status=DIRTY
cleanup() {
  rc=$?
  trap - EXIT INT TERM
  if [[ -n "$current" ]]; then
    echo "STOPPING_OWNED_UNIT=$current" | tee -a "$folder/summary.log"
    sudo systemctl stop "$current" >> "$folder/summary.log" 2>&1 || true
  fi
  printf 'FINAL_STATUS=%s EXIT_CODE=%s\n' "$status" "$rc" | tee -a "$folder/summary.log"
  printf 'GPU_REUSE_SAFE=NOT_VERIFIED\nN1_REAL_GPU_GRANT=NOT_ADMITTED\n' | tee -a "$folder/summary.log"
  exit "$rc"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

# This is the only stage that needs administrator auth, for fixed system manager calls.
sudo -v
require_idle() {
  for service in gdm.service ai-gateway.service ai-bridge.service ollama.service comfyui.service ai-bridge-analysis.timer; do
    [[ "$(systemctl is-active "$service" 2>/dev/null || true)" == inactive ]] ||
      { echo "BLOCKED: service changed $service" >&2; return 1; }
  done
  local kfd fd_result fd_status
  kfd=$(find /sys/class/kfd/kfd/proc -mindepth 1 -maxdepth 1 -printf '%f ' 2>&1) || return 1
  set +e
  fd_result=$(sudo -n /usr/bin/fuser /dev/kfd /dev/dri/renderD128 2>> "$folder/summary.log")
  fd_status=$?
  set -e
  (( fd_status == 0 || fd_status == 1 )) || return 1
  [[ -z "$kfd" && -z "$fd_result" ]] ||
    { echo "BLOCKED: GPU owners: kfd=$kfd fd=$fd_result" >&2; return 1; }
}
postflight() {
  local stable=0 i
  for i in {1..40}; do
    if require_idle; then stable=$((stable+1)); else stable=0; fi
    echo "GPU_POST_SAMPLE=$i STABLE_EMPTY=$stable" >> "$folder/summary.log"
    if (( stable >= 3 )); then return 0; fi
    sleep 0.25
  done
  echo 'BLOCKED: postflight not verified' >&2
  return 1
}
unit_properties=(
  -p 'DevicePolicy=strict'
  -p 'DeviceAllow=/dev/kfd rw'
  -p 'DeviceAllow=/dev/dri/renderD128 rw'
  -p 'PrivateDevices=no'
  -p 'NoNewPrivileges=yes'
  -p 'KillMode=control-group'
  -p 'Restart=no'
  -p 'RuntimeMaxSec=95s'
  -p 'TimeoutStopSec=18s'
)
start_unit() {
  local unit=$1 user=$2 group=$3
  shift 3
  require_idle
  echo "START_UNIT=$unit user=$user" | tee -a "$folder/summary.log"
  current="$unit"
  sudo systemd-run --system --collect --service-type=exec --unit="$unit"     -p "User=$user" -p "Group=$group"     "${unit_properties[@]}" "$@" >> "$folder/summary.log" 2>&1
  # Runtime policy must actually be installed by the system manager.
  local x
  x=$(systemctl show "$unit" --no-pager -p ActiveState -p User -p DevicePolicy -p ControlGroup -p MainPID)
  printf '%s\n' "$x" | tee -a "$folder/summary.log"
  grep -q '^ActiveState=active$' <<<"$x"
  grep -q "^User=$user$" <<<"$x"
  grep -q '^DevicePolicy=strict$' <<<"$x"
  grep -Eq '^MainPID=[1-9][0-9]+$' <<<"$x"
}
verify_live_engine() {
  local unit=$current cg holder_text rc pid holder_cgroup count=0
  [[ -n "$unit" ]] || return 1
  cg=$(systemctl show "$unit" --value -p ControlGroup)
  [[ "$cg" == "/system.slice/$unit" ]] || {
    echo "BLOCKED: cgroup of GPU engine unexpected: $cg" >&2; return 1;
  }
  set +e
  holder_text=$(sudo -n /usr/bin/fuser /dev/kfd /dev/dri/renderD128 2>> "$folder/summary.log")
  rc=$?
  set -e
  (( rc == 0 )) || {
    echo "BLOCKED: no verified active GPU process for unit $unit" >&2; return 1;
  }
  for pid in $holder_text; do
    [[ "$pid" =~ ^[0-9]+$ ]] || return 1
    [[ -r "/proc/$pid/cgroup" ]] || return 1
    holder_cgroup=$(cat "/proc/$pid/cgroup")
    [[ "$holder_cgroup" == "0::$cg" || "$holder_cgroup" == "0::$cg/"* ]] || {
      echo "BLOCKED: foreign GPU owner $pid in $holder_cgroup" >&2; return 1;
    }
    echo "GPU_OWNER pid=$pid cgroup=$holder_cgroup unit=$unit" >> "$folder/summary.log"
    count=$((count+1))
  done
  (( count > 0 )) || return 1
}
stop_unit() {
  local unit=$current
  [[ -n "$unit" ]] || return 1
  echo "STOP_UNIT=$unit" | tee -a "$folder/summary.log"
  sudo systemctl stop "$unit" >> "$folder/summary.log" 2>&1
  local s
  s=$(systemctl is-active "$unit" 2>/dev/null || true)
  [[ "$s" == inactive || "$s" == unknown ]] || { echo "STOP_FAILED: $unit state=$s"; return 1; }
  # Never clear ownership while an old systemd cgroup still contains tasks.
  if [[ -d "/sys/fs/cgroup/system.slice/$unit" ]]; then
    [[ ! -s "/sys/fs/cgroup/system.slice/$unit/cgroup.procs" ]] || {
      echo "STOP_FAILED: cgroup still has tasks: $unit" >&2; return 1;
    }
  fi
  postflight
  current=""
  completed=$((completed+1))
  echo "ENGINE_STAGE_$completed=PASS" | tee -a "$folder/summary.log"
}
await_http() {
  local url=$1 i
  for i in {1..85}; do
    if curl --noproxy '*' -fsS --max-time 2 "$url" > "$folder/http.json" 2>/dev/null; then return 0; fi
    [[ -n "$current" ]] && [[ "$(systemctl is-active "$current" 2>/dev/null || true)" == active ]] || return 1
    sleep 0.5
  done
  return 1
}
require_idle
echo 'BEGIN_OLLAMA_VULKAN_LIGHT_MODEL'
start_unit "ai-rm-$id-ollama.service" ollama ollama   -E 'OLLAMA_HOST=127.0.0.1:11590'   -E 'OLLAMA_MODELS=/usr/share/ollama/.ollama/models'   -E 'OLLAMA_KEEP_ALIVE=0' -E 'OLLAMA_MAX_LOADED_MODELS=1'   -E 'OLLAMA_VULKAN=1' -E 'OLLAMA_IGPU_ENABLE=1' -E 'OLLAMA_NOPRUNE=true'   /usr/local/bin/ollama serve
await_http http://127.0.0.1:11590/api/version
curl --noproxy '*' -fsS --max-time 65 -H 'Content-Type: application/json'   -d '{"model":"bge-m3","input":"systemd rm exclusive pilot","keep_alive":"30s"}'   http://127.0.0.1:11590/api/embed > "$folder/ollama.json"
python3 -c 'import json,sys; x=json.load(open(sys.argv[1])); assert len(x["embeddings"][0])==1024' "$folder/ollama.json"
verify_live_engine
stop_unit

echo 'BEGIN_COMFYUI_ROCM_INITIALIZATION'
mkdir -p "$folder"/{user,input,output,temp}
start_unit "ai-rm-$id-comfy.service" harrypotter harrypotter   -p 'WorkingDirectory=/opt/comfyui/ComfyUI'   /opt/comfyui/venv/bin/python /opt/comfyui/ComfyUI/main.py   --listen 127.0.0.1 --port 8189 --disable-auto-launch   --disable-all-custom-nodes --preview-method none   --user-directory "$folder/user" --input-directory "$folder/input"   --output-directory "$folder/output" --temp-directory "$folder/temp"   --models-directory /opt/comfyui/data/models
await_http http://127.0.0.1:8189/system_stats
python3 -c 'import json,sys; x=json.load(open(sys.argv[1])); assert any("AMD Radeon 890M" in d.get("name","") for d in x["devices"])' "$folder/http.json"
verify_live_engine
stop_unit

echo 'BEGIN_VISION_FIXED_ROCM_64'
require_idle
sudo systemd-run --system --wait --collect --pipe --service-type=exec   --unit="ai-rm-$id-vision.service" -p User=harrypotter   -p Group=harrypotter "${unit_properties[@]}"   /opt/comfyui/venv/bin/python -I   "$BASE/src/ai_bridge/gateway/rocm_test_worker.py" > "$folder/vision.log" 2>&1
grep -q '"status": "WORKER_LOCAL_SYNC"' "$folder/vision.log"
postflight
completed=$((completed+1))
echo "ENGINE_STAGE_$completed=PASS" | tee -a "$folder/summary.log"

if (( completed != 3 )); then echo "BLOCKED: incomplete stages" >&2; exit 2; fi
status=LOCAL_SYSTEMD_HANDOFF_PASS_3_OF_3
echo "RESULT=$status" | tee -a "$folder/summary.log"
echo "GLOBAL_GPU_REUSE_SAFE=NOT_VERIFIED" | tee -a "$folder/summary.log"
