#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
DATA="/srv/ai-data/training/p5"
MODEL="$DATA/models/Qwen3.8-27B-buffered-512m"
DATASET="$ROOT/deploy/stage-p5/training/diagnostic_reasoning_v1/diagnostic_reasoning_v1_replay_train.jsonl"
BASE_ADAPTER="$DATA/adapters/automotive-specialization-v1/current"
IMAGE="ai-platform-p5-train:rocm7.2.1-v1"
EXPECTED_IMAGE_ID="sha256:415b8e68c15d5bf9f7eeb6c4b697327953c600c875456ec5b12fccc1eb5414f8"
OPT_STEPS=40
MAX_LENGTH=768
LORA_R=8
LR=0.00001
CGROUP_MEMORY="${P5_CGROUP_MEMORY:-48g}"
CGROUP_SWAP="${P5_CGROUP_SWAP:-$CGROUP_MEMORY}"
MIN_HOST_AVAILABLE_KIB="${P5_MIN_HOST_AVAILABLE_KIB:-8388608}"
MAX_INITIAL_VRAM="${P5_MAX_INITIAL_VRAM:-2147483648}"
ALLOW_QUIESCED_COMFYUI="${P5_ALLOW_QUIESCED_COMFYUI:-0}"
RELEASE_TIMEOUT="${P5_RELEASE_TIMEOUT_SECONDS:-120}"
RUN_ID="${P5_RUN_ID:-diagnostic-reasoning-v1-$(date -u +%Y%m%dT%H%M%SZ)}"
[[ "$RUN_ID" =~ ^[a-zA-Z0-9][a-zA-Z0-9_-]*$ ]] || { echo "invalid run ID" >&2; exit 1; }
export P5_RUN_ID="$RUN_ID"
CONTAINER_NAME="p512-$RUN_ID"
ADAPTER_ROOT="$DATA/adapters/diagnostic-reasoning-v1"
OUT="$ADAPTER_ROOT/$RUN_ID"
LOG="$DATA/logs/p512-$RUN_ID.log"
TELEM="$DATA/logs/p512-$RUN_ID-host.csv"
EVIDENCE="$DATA/evidence/p512/$RUN_ID"
FAIL_MARKER="$EVIDENCE/watchdog_failure.txt"
GIT_SHA="$(git -C "$ROOT" rev-parse HEAD)"
GPU_ERROR_RE='MES.*WAIT_REG_MEM|MES ring buffer is full|amdgpu.*(GPU reset|reset begin|reset succeeded|reset failed|GPU fault|page fault|GPUVM)|kfd.*(error|fault)|IOMMU.*(amdgpu|AMD-Vi.*fault)'

if [[ "${1:-}" != "--reserved" ]]; then
  exec python3 "$ROOT/deploy/stage-p5/training/diagnostic_reasoning_v1/resource_guard.py"     --evidence "$EVIDENCE" --container "$CONTAINER_NAME" --training-manifest "$OUT/p512_training_manifest.json" -- bash "$0" --reserved
fi
[[ -n "${P512_LEASE_ID:-}" && "${P512_LEASE_STATUS:-}" == active ]] || exit 46
[[ "$(docker image inspect "$IMAGE" --format '{{.Id}}')" == "$EXPECTED_IMAGE_ID" ]] || exit 48
command -v journalctl >/dev/null
command -v lsof >/dev/null
# journalctl may succeed without kernel visibility; require a nonempty boot log.
[[ -n "$(journalctl -b -k --no-pager)" ]] || exit 47

count_gpu_errors() {
  local logs
  logs="$(journalctl -b -k --no-pager)" || return 1
  [[ -n "$logs" ]] || return 1
  printf '%s\n' "$logs" | grep -Eic "$GPU_ERROR_RE" || [[ $? == 1 ]]
}
snapshot_gpu_errors() {
  journalctl -b -k --no-pager 2>/dev/null | grep -Ei "$GPU_ERROR_RE" || true
}
mem_available_kib() {
  awk '/MemAvailable:/ {print $2}' /proc/meminfo
}
vram_used() {
  cat /sys/class/drm/card0/device/mem_info_vram_used
}
gpu_busy() {
  cat /sys/class/drm/card0/device/gpu_busy_percent 2>/dev/null || echo -1
}

python3 "$ROOT/deploy/stage-p5/training/diagnostic_reasoning_v1/validate_diagnostic_reasoning_v1.py" >/tmp/p512-validate.txt
grep -q '^P5_12_DIAGNOSTIC_READINESS=PASS$' /tmp/p512-validate.txt

test -f "$MODEL/model.safetensors.index.json"
test -f "$BASE_ADAPTER/adapter_config.json"
BASE_ADAPTER_REAL="$(realpath "$BASE_ADAPTER")"
case "$BASE_ADAPTER_REAL" in "$DATA"/*) ;; *) echo "P5_12=BLOCKED parent_adapter_outside_data_root" >&2; exit 40;; esac
test -f "$BASE_ADAPTER_REAL/adapter_model.safetensors"

mkdir -p "$ADAPTER_ROOT" "$(dirname "$LOG")" "$EVIDENCE"
if [ -e "$OUT" ] && find "$OUT" -mindepth 1 -print -quit 2>/dev/null | grep -q .; then
  echo "P5_12=BLOCKED output_exists_nonempty=$OUT" >&2
  exit 41
fi
mkdir -p "$OUT"

VRAM_BEFORE="$(vram_used)"
MEM_BEFORE="$(mem_available_kib)"
[[ "$VRAM_BEFORE" =~ ^[0-9]+$ && "$MEM_BEFORE" =~ ^[0-9]+$ ]] || exit 49
OLLAMA_BEFORE="$(ollama ps)"
PREFLIGHT_JSON="$(python3 - "$ROOT" "$ALLOW_QUIESCED_COMFYUI" <<'PYPREFLIGHT'
import json,sys
sys.path.insert(0,sys.argv[1]+'/deploy/stage-p5/training/diagnostic_reasoning_v1')
from resource_guard import local_preflight
print(json.dumps(local_preflight(sys.argv[2]=='1')))
PYPREFLIGHT
)"
KFD_OWNERS="$PREFLIGHT_JSON"
KFD_BLOCKERS=""
GPU_BASELINE="$(count_gpu_errors)"
export P512_GPU_BASELINE="$GPU_BASELINE" P512_PARENT_REALPATH="$BASE_ADAPTER_REAL"
sha256sum "$BASE_ADAPTER_REAL/adapter_model.safetensors" "$DATASET" >"$EVIDENCE/input_sha256.txt"
printf 'lease_id=%s\nlease_status=%s\n' "$P512_LEASE_ID" "$P512_LEASE_STATUS" >"$EVIDENCE/reservation.txt"
snapshot_gpu_errors >"$EVIDENCE/kernel_gpu_errors_before.txt"
{
  echo "git_sha=$GIT_SHA"
  echo "run_id=$RUN_ID"
  echo "vram_before=$VRAM_BEFORE"
  echo "mem_available_kib_before=$MEM_BEFORE"
  echo "gpu_busy_before=$(gpu_busy)"
  echo "gpu_error_baseline=$GPU_BASELINE"
  echo "kfd_owners=${KFD_OWNERS:-none}"
  echo "kfd_blockers=${KFD_BLOCKERS:-none}"
  echo "allow_quiesced_comfyui=$ALLOW_QUIESCED_COMFYUI"
  printf 'ollama_ps_before=%q\n' "$OLLAMA_BEFORE"
  echo "parent_adapter=$BASE_ADAPTER_REAL"
  echo "dataset=$DATASET"
} >"$EVIDENCE/preflight.txt"

if (( VRAM_BEFORE > MAX_INITIAL_VRAM )); then
  echo "P5_12=BLOCKED gpu_vram_already_used=$VRAM_BEFORE" >&2
  exit 42
fi
if printf '%s\n' "$OLLAMA_BEFORE" | tail -n +2 | grep -q .; then
  echo "P5_12=BLOCKED ollama_model_resident" >&2
  printf '%s\n' "$OLLAMA_BEFORE" >&2
  exit 43
fi
if (( MEM_BEFORE < MIN_HOST_AVAILABLE_KIB )); then
  echo "P5_12=BLOCKED mem_available_kib=$MEM_BEFORE" >&2
  exit 44
fi
if [ -n "${KFD_BLOCKERS// }" ]; then
  echo "P5_12=BLOCKED unexpected_kfd_owner=$KFD_BLOCKERS" >&2
  exit 45
fi

printf "timestamp,vram_used_bytes,mem_available_kib,gpu_busy_percent,gpu_error_count\n" >"$TELEM"
(
  while true; do
    ts="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    vu="$(vram_used)" || vu=unreadable
    ma="$(mem_available_kib)" || ma=unreadable
    busy="$(gpu_busy)"
    if ! errors="$(count_gpu_errors)" || ! [[ "$vu" =~ ^[0-9]+$ && "$ma" =~ ^[0-9]+$ ]]; then
      echo "P5_12_WATCHDOG telemetry_unreadable" >"$FAIL_MARKER"
      docker kill "$CONTAINER_NAME" >/dev/null 2>&1 || true
      exit 90
    fi
    printf "%s,%s,%s,%s,%s\n" "$ts" "$vu" "$ma" "$busy" "$errors" >>"$TELEM"
    if (( ma < MIN_HOST_AVAILABLE_KIB )); then
      echo "P5_12_HOST_WATCHDOG mem_available_kib=$ma threshold=$MIN_HOST_AVAILABLE_KIB" >"$FAIL_MARKER"
      docker kill "$CONTAINER_NAME" >/dev/null 2>&1 || true
      exit 88
    fi
    if (( errors > GPU_BASELINE )); then
      echo "P5_12_GPU_WATCHDOG baseline=$GPU_BASELINE current=$errors" >"$FAIL_MARKER"
      snapshot_gpu_errors >"$EVIDENCE/kernel_gpu_errors_watchdog.txt"
      docker kill "$CONTAINER_NAME" >/dev/null 2>&1 || true
      exit 89
    fi
    sleep 3
  done
) &
MON_PID=$!

cleanup_monitor() {
  kill "$MON_PID" >/dev/null 2>&1 || true
  wait "$MON_PID" >/dev/null 2>&1 || true
}
trap cleanup_monitor EXIT
trap 'docker kill "$CONTAINER_NAME" >/dev/null 2>&1 || true; exit 130' INT
trap 'docker kill "$CONTAINER_NAME" >/dev/null 2>&1 || true; exit 143' TERM

UIDN="$(id -u)"
GIDN="$(id -g)"
RGID="$(getent group render | cut -d: -f3)"
VGID="$(getent group video | cut -d: -f3)"
MODEL_IN="/p5/${MODEL#"$DATA"/}"
ADAPTER_IN="/p5/${BASE_ADAPTER_REAL#"$DATA"/}"
OUT_IN="/p5/adapters/diagnostic-reasoning-v1/$RUN_ID"

[[ ! -f "$FAIL_MARKER" ]] && kill -0 "$MON_PID" || exit 80
set +e
docker run --rm --name "$CONTAINER_NAME"   --network=none   --memory="$CGROUP_MEMORY" --memory-swap="$CGROUP_SWAP"   --user "$UIDN:$GIDN" --group-add "$RGID" --group-add "$VGID"   --device=/dev/kfd --device=/dev/dri --ipc=host --shm-size=8g   -e HOME=/p5/tmp/home -e HF_HOME=/p5/hf-cache   -e P512_LEASE_ID -e P512_LEASE_STATUS -e P512_GPU_BASELINE -e P512_PARENT_REALPATH -e P512_EVIDENCE -e P5_GIT_SHA="$GIT_SHA" -e HSA_USE_SVM=0   -v "$DATA:/p5" -v "$ROOT:/workspace:ro" "$IMAGE"   python3 /workspace/deploy/stage-p5/training/diagnostic_reasoning_v1/train_diagnostic_reasoning_v1.py     --model-dir "$MODEL_IN"     --dataset /workspace/deploy/stage-p5/training/diagnostic_reasoning_v1/diagnostic_reasoning_v1_replay_train.jsonl     --output-dir "$OUT_IN"     --adapter-dir "$ADAPTER_IN"     --optimizer-steps "$OPT_STEPS" --max-length "$MAX_LENGTH"     --seed 20261003 --lora-r "$LORA_R" --lr "$LR"     2>&1 | tee "$LOG"
TRAIN_RC=${PIPESTATUS[0]}
set -e

kill -0 "$MON_PID" || { [[ -f "$FAIL_MARKER" ]] || echo "watchdog_died" >"$FAIL_MARKER"; }
cleanup_monitor
trap - EXIT INT TERM

GPU_FINAL="$(count_gpu_errors)"
snapshot_gpu_errors >"$EVIDENCE/kernel_gpu_errors_after.txt"
if [ -f "$FAIL_MARKER" ]; then
  cat "$FAIL_MARKER" >&2
  echo "P5_12=FAILED watchdog_triggered output_preserved=$OUT" >&2
  exit 80
fi
if (( TRAIN_RC != 0 )); then
  echo "P5_12=FAILED training_rc=$TRAIN_RC output_preserved=$OUT" >&2
  exit "$TRAIN_RC"
fi
if (( GPU_FINAL != GPU_BASELINE )); then
  echo "P5_12=FAILED gpu_error_delta baseline=$GPU_BASELINE final=$GPU_FINAL" >&2
  exit 81
fi

python3 - "$OUT" "$DATASET" <<'PY'
import hashlib, json, math, struct, sys
from pathlib import Path
out=Path(sys.argv[1]); dataset=Path(sys.argv[2])
cfg=json.loads((out/"adapter_config.json").read_text())
if cfg.get("r") != 8:
    raise SystemExit("adapter rank is not 8")
adapter=out/"adapter_model.safetensors"
if not adapter.is_file() or adapter.stat().st_size < 1024:
    raise SystemExit("adapter safetensors missing/too small")
with adapter.open("rb") as f:
    raw=f.read(8)
    if len(raw)!=8: raise SystemExit("bad safetensors prefix")
    size=struct.unpack("<Q",raw)[0]
    header=json.loads(f.read(size))
    tensors=[k for k in header if k!="__metadata__"]
    if not tensors: raise SystemExit("no tensors in adapter")
m=json.loads((out/"p512_training_manifest.json").read_text())
if m.get("status")!="TRAINING_INTEGRITY_PASS_QUALITY_PENDING":
    raise SystemExit("training manifest status invalid")
if m.get("quality_acceptance")!="PENDING_POST_TRAINING_SMOKE":
    raise SystemExit("quality boundary invalid")
if len(m.get("optimizer_steps",[]))!=40 or len(m.get("microsteps",[]))!=160:
    raise SystemExit("step/microstep count invalid")
if m.get("config",{}).get("microsteps")!=160 or m.get("config",{}).get("optimizer_steps")!=40:
    raise SystemExit("training config count invalid")
if m.get("token_contract",{}).get("truncated_records")!=0:
    raise SystemExit("token truncation occurred")
for row in m["microsteps"]:
    if not math.isfinite(float(row["loss"])):
        raise SystemExit("non-finite microstep loss")
for row in m["optimizer_steps"]:
    if not math.isfinite(float(row["grad_norm"])) or not math.isfinite(float(row["mean_loss"])):
        raise SystemExit("non-finite optimizer metric")
h=hashlib.sha256(dataset.read_bytes()).hexdigest()
if m.get("dataset_sha256")!=h:
    raise SystemExit("runtime dataset hash mismatch")
if m.get("adapter_sha256")!=hashlib.sha256(adapter.read_bytes()).hexdigest():
    raise SystemExit("runtime adapter hash mismatch")
print("P5_12_ADAPTER_VALIDATION=PASS")
PY

released=0
for ((i=0; i<RELEASE_TIMEOUT; i++)); do
  vu="$(vram_used)"
  if (( vu <= MAX_INITIAL_VRAM )) && python3 - "$ROOT" "$ALLOW_QUIESCED_COMFYUI" <<'PYRELEASE'
import sys
sys.path.insert(0,sys.argv[1]+'/deploy/stage-p5/training/diagnostic_reasoning_v1')
from resource_guard import local_preflight
local_preflight(sys.argv[2]=='1')
PYRELEASE
  then
    released=1
    break
  fi
  sleep 1
done
if (( released != 1 )); then
  echo "P5_12=FAILED resource_release_timeout vram=$(vram_used)" >&2
  exit 82
fi

GPU_POST_RELEASE="$(count_gpu_errors)"
if (( GPU_POST_RELEASE != GPU_BASELINE )); then
  echo "P5_12=FAILED gpu_error_after_release baseline=$GPU_BASELINE final=$GPU_POST_RELEASE" >&2
  exit 83
fi


{
  echo "training_rc=$TRAIN_RC"
  echo "gpu_error_baseline=$GPU_BASELINE"
  echo "gpu_error_final=$GPU_POST_RELEASE"
  echo "vram_after_release=$(vram_used)"
  echo "mem_available_kib_after=$(mem_available_kib)"
  echo "gpu_busy_after=$(gpu_busy)"
  echo "adapter_output=$OUT"
} >"$EVIDENCE/postflight.txt"

python3 - "$OUT/p512_training_manifest.json" "$GPU_POST_RELEASE" <<'PYMANIFEST'
import json,sys
from pathlib import Path
p=Path(sys.argv[1]); m=json.loads(p.read_text())
m['host_watchdog_status']='PASS'
m['gpu_error_final']=int(sys.argv[2])
p.write_text(json.dumps(m,indent=2,sort_keys=True)+'\n')
PYMANIFEST

echo "P5_12_DIAGNOSTIC_TRAINING=PASS"
echo "P5_12_RUN_ID=$RUN_ID"
echo "P5_12_ADAPTER=$OUT"
echo "P5_12_LOG=$LOG"
echo "P5_12_TELEMETRY=$TELEM"
echo "P5_12_EVIDENCE=$EVIDENCE"
