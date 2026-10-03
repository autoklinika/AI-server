#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
DATA="/srv/ai-data/training/p5"
MODEL="$DATA/models/Qwen3.8-27B-buffered-512m"
DATASET="$ROOT/deploy/stage-p5/training/wvc_v1/data/train.jsonl"
IMAGE="${P5_TRAIN_IMAGE:-ai-platform-p5-train:rocm7.2.1-v1}"
EXPECTED_IMAGE_ID="sha256:415b8e68c15d5bf9f7eeb6c4b697327953c600c875456ec5b12fccc1eb5414f8"
OPT_STEPS=40
MAX_LENGTH=8192
LORA_R="${P5_LORA_R:-8}"
LR="${P5_LR:-0.00002}"
CGROUP_MEMORY="${P5_CGROUP_MEMORY:-48g}"
CGROUP_SWAP="${P5_CGROUP_SWAP:-$CGROUP_MEMORY}"
MIN_HOST_AVAILABLE_KIB="${P5_MIN_HOST_AVAILABLE_KIB:-8388608}"
MAX_INITIAL_VRAM="${P5_MAX_INITIAL_VRAM:-2147483648}"
ALLOW_QUIESCED_COMFYUI="${P5_ALLOW_QUIESCED_COMFYUI:-0}"
RELEASE_TIMEOUT="${P5_RELEASE_TIMEOUT_SECONDS:-120}"
RUN_ID="${P5_RUN_ID:-wvc-v1-$(date -u +%Y%m%dT%H%M%SZ)}"
CONTAINER_NAME="wvc-$RUN_ID"
ADAPTER_ROOT="$DATA/adapters/wvc-advisory-v1"
OUT="$ADAPTER_ROOT/$RUN_ID"
LOG="$DATA/logs/wvc-$RUN_ID.log"
TELEM="$DATA/logs/wvc-$RUN_ID-host.csv"
EVIDENCE="$DATA/evidence/wvc/$RUN_ID"
FAIL_MARKER="$EVIDENCE/watchdog_failure.txt"
GIT_SHA="$(git -C "$ROOT" rev-parse HEAD)"
GPU_ERROR_RE='MES.*WAIT_REG_MEM|MES ring buffer is full|amdgpu.*(GPU reset|reset begin|reset succeeded|reset failed|GPU fault|page fault|GPUVM)|kfd.*(error|fault)|IOMMU.*(amdgpu|AMD-Vi.*fault)'

if [[ "${1:-}" != "--reserved" ]]; then
  exec python3 "$ROOT/deploy/stage-p5/training/wvc_v1/resource_guard.py"     --evidence "$EVIDENCE" --container "$CONTAINER_NAME"     --training-manifest "$OUT/wvc_training_manifest.json"     -- bash "$0" --reserved
fi
[[ -n "${WVC_LEASE_ID:-}" && "${WVC_LEASE_STATUS:-}" == active ]] || { echo "WVC=BLOCKED no_active_resource_lease"; exit 46; }
[[ "$(docker image inspect "$IMAGE" --format '{{.Id}}')" == "$EXPECTED_IMAGE_ID" ]] || { echo "WVC=BLOCKED unexpected_training_image"; exit 48; }

count_gpu_errors() {
  local journal
  journal="$(journalctl -b -k --no-pager)" || { echo 999999999; return; }
  printf '%s\n' "$journal" | grep -Eic "$GPU_ERROR_RE" || true
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

# Host-side gates use the project environment; the GPU image stays unchanged.
PYTHON="${WVC_PYTHON:-/home/harrypotter/AI-server/.venv/bin/python}"
if [ ! -x "$PYTHON" ]; then PYTHON=python3; fi
mkdir -p "$EVIDENCE" "$(dirname "$LOG")"
exec > >(tee -a "$LOG") 2>&1
exec 9>"$DATA/.wvc-gpu-job.lock"
flock -n 9 || { echo "WVC=BLOCKED another_wvc_job"; exit 46; }
export PYTHONPATH="$ROOT/src"
"$PYTHON" "$ROOT/deploy/stage-p5/training/wvc_v1/dataset.py" validate >"$EVIDENCE/gates.json"
"$PYTHON" -m pytest -p no:cacheprovider "$ROOT/tests/test_wvc_domain.py" \
  "$ROOT/tests/test_analysis_v12.py" "$ROOT/tests/test_analysis_v12_1.py" \
  "$ROOT/tests/test_analysis_v12_2.py" "$ROOT/tests/test_analysis_service_v12_2.py" \
  "$ROOT/tests/test_stage_p5_wvc.py" >"$EVIDENCE/unit-tests.txt"
{
  echo "pid=$$"
  echo "container=$CONTAINER_NAME"
  echo "worktree=$ROOT"
  echo "branch=$(git -C "$ROOT" symbolic-ref --short -q HEAD || echo DETACHED)"
  echo "git_sha=$GIT_SHA"
  echo "dataset=$DATASET"
  echo "manifest=$ROOT/deploy/stage-p5/training/wvc_v1/data/manifest.json"
  echo "output=$OUT"
  echo "log=$LOG"
  echo "config=$ROOT/deploy/stage-p5/training/wvc_v1/config.json"
} >"$EVIDENCE/job.txt"
git -C "$ROOT" diff >"$EVIDENCE/worktree.patch"
sha256sum "$ROOT"/deploy/stage-p5/training/wvc_v1/*.py "$ROOT"/deploy/stage-p5/training/wvc_v1/*.sh >"$EVIDENCE/code-sha256.txt"
# Fail closed: absent devices/telemetry never mean an idle healthy GPU.
test -c /dev/kfd && test -d /dev/dri || { echo "WVC=BLOCKED no_gpu_devices"; exit 47; }
docker info >/dev/null || { echo "WVC=BLOCKED docker_unavailable"; exit 48; }
test -r /sys/class/drm/card0/device/mem_info_vram_used || exit 49
command -v lsof >/dev/null
command -v ollama >/dev/null
ollama ps >"$EVIDENCE/ollama.txt" || exit 49
journalctl -b -k --no-pager >"$EVIDENCE/kernel-access.txt"
test -s "$EVIDENCE/kernel-access.txt"
grep -qi 'amdgpu' "$EVIDENCE/kernel-access.txt" || { echo "WVC=BLOCKED kernel_telemetry_unavailable"; exit 49; }
test -f "$MODEL/model.safetensors.index.json"

mkdir -p "$ADAPTER_ROOT" "$(dirname "$LOG")" "$EVIDENCE" "$OUT"
test -f "$OUT/baseline.json" || { echo "WVC=BLOCKED baseline_missing=$OUT/baseline.json" >&2; exit 41; }
if find "$OUT" -mindepth 1 -maxdepth 1 ! -name baseline.json -print -quit 2>/dev/null | grep -q .; then
  echo "WVC=BLOCKED output_contains_nonbaseline_artifacts=$OUT" >&2
  exit 41
fi

VRAM_BEFORE="$(vram_used)"
MEM_BEFORE="$(mem_available_kib)"
OLLAMA_BEFORE="$(ollama ps 2>/dev/null || true)"
KFD_OWNERS="$(lsof -t /dev/kfd 2>/dev/null | sort -u | tr '\n' ' ' || true)"
KFD_BLOCKERS="$KFD_OWNERS"
if [ "$ALLOW_QUIESCED_COMFYUI" = "1" ] && [ -n "${KFD_OWNERS// }" ]; then
  KFD_BLOCKERS=""
  for pid in $KFD_OWNERS; do
    state="$(awk '/^State:/ {print $2}' "/proc/$pid/status" 2>/dev/null || true)"
    owner_uid="$(stat -c '%u' "/proc/$pid" 2>/dev/null || true)"
    cgroup="$(cat "/proc/$pid/cgroup" 2>/dev/null || true)"
    if [ "$owner_uid" = "$(id -u)" ] && { [ "$state" = "T" ] || [ "$state" = "t" ]; } && printf '%s\n' "$cgroup" | grep -qx '0::/system.slice/comfyui.service'; then
      continue
    fi
    KFD_BLOCKERS="$KFD_BLOCKERS $pid"
  done
fi
GPU_BASELINE="$(count_gpu_errors)"
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
  echo "parent_adapter=NONE"
  echo "dataset=$DATASET"
} >"$EVIDENCE/preflight.txt"

if (( VRAM_BEFORE > MAX_INITIAL_VRAM )); then
  echo "WVC=BLOCKED gpu_vram_already_used=$VRAM_BEFORE" >&2
  exit 42
fi
if printf '%s\n' "$OLLAMA_BEFORE" | tail -n +2 | grep -q .; then
  echo "WVC=BLOCKED ollama_model_resident" >&2
  printf '%s\n' "$OLLAMA_BEFORE" >&2
  exit 43
fi
if (( MEM_BEFORE < MIN_HOST_AVAILABLE_KIB )); then
  echo "WVC=BLOCKED mem_available_kib=$MEM_BEFORE" >&2
  exit 44
fi
if [ -n "${KFD_BLOCKERS// }" ]; then
  echo "WVC=BLOCKED unexpected_kfd_owner=$KFD_BLOCKERS" >&2
  exit 45
fi

printf "timestamp,vram_used_bytes,mem_available_kib,gpu_busy_percent,gpu_error_count\n" >"$TELEM"
(
  while true; do
    ts="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    vu="$(vram_used)"
    ma="$(mem_available_kib)"
    busy="$(gpu_busy)"
    errors="$(count_gpu_errors)"
    printf "%s,%s,%s,%s,%s\n" "$ts" "$vu" "$ma" "$busy" "$errors" >>"$TELEM"
    if (( ma < MIN_HOST_AVAILABLE_KIB )); then
      echo "WVC_HOST_WATCHDOG mem_available_kib=$ma threshold=$MIN_HOST_AVAILABLE_KIB" >"$FAIL_MARKER"
      docker kill "$CONTAINER_NAME" >/dev/null 2>&1 || true
      exit 88
    fi
    if (( errors > GPU_BASELINE )); then
      echo "WVC_GPU_WATCHDOG baseline=$GPU_BASELINE current=$errors" >"$FAIL_MARKER"
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
trap 'docker kill "$CONTAINER_NAME" >/dev/null 2>&1 || true; exit 130' INT TERM

UIDN="$(id -u)"
GIDN="$(id -g)"
RGID="$(getent group render | cut -d: -f3)"
VGID="$(getent group video | cut -d: -f3)"
MODEL_IN="/model/Qwen3.8-27B-buffered-512m"
OUT_IN="/wvc/$RUN_ID"

set +e
docker run --rm --name "$CONTAINER_NAME" \
  --network=none --memory="$CGROUP_MEMORY" --memory-swap="$CGROUP_SWAP" \
  --user "$UIDN:$GIDN" --group-add "$RGID" --group-add "$VGID" \
  --device=/dev/kfd --device=/dev/dri --ipc=host --shm-size=8g \
  -e HOME=/tmp -e HF_HOME=/tmp/hf-cache -e PYTHONPATH=/workspace/src \
  -e P5_GIT_SHA="$GIT_SHA" -e HSA_USE_SVM=0 \
  -v "$MODEL:$MODEL_IN:ro" -v "$ADAPTER_ROOT:/wvc" -v "$ROOT:/workspace:ro" "$IMAGE" \
  python3 /workspace/deploy/stage-p5/training/wvc_v1/train.py     --model-dir "$MODEL_IN"     --dataset /workspace/deploy/stage-p5/training/wvc_v1/data/train.jsonl     --output-dir "$OUT_IN" --optimizer-steps "$OPT_STEPS"     --max-length "$MAX_LENGTH" --seed 20261003 --lora-r "$LORA_R" --lr "$LR"

TRAIN_RC=$?
set -e

cleanup_monitor
trap - EXIT INT TERM

GPU_FINAL="$(count_gpu_errors)"
snapshot_gpu_errors >"$EVIDENCE/kernel_gpu_errors_after.txt"
if [ -f "$FAIL_MARKER" ]; then
  cat "$FAIL_MARKER" >&2
  echo "WVC=FAILED watchdog_triggered output_preserved=$OUT" >&2
  exit 80
fi
if (( TRAIN_RC != 0 )); then
  echo "WVC=FAILED training_rc=$TRAIN_RC output_preserved=$OUT" >&2
  exit "$TRAIN_RC"
fi
if (( GPU_FINAL != GPU_BASELINE )); then
  echo "WVC=FAILED gpu_error_delta baseline=$GPU_BASELINE final=$GPU_FINAL" >&2
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
m=json.loads((out/"wvc_training_manifest.json").read_text())
if m.get("status")!="TRAINING_INTEGRITY_PASS_QUALITY_PENDING":
    raise SystemExit("training manifest status invalid")
if m.get("quality_acceptance")!="PENDING_FUTURE_INDEPENDENT_EVALUATION":
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
print("WVC_ADAPTER_VALIDATION=PASS")
PY

released=0
for ((i=0; i<RELEASE_TIMEOUT; i++)); do
  vu="$(vram_used)"
  owners="$(lsof -t /dev/kfd 2>/dev/null | sort -u | tr '\n' ' ' || true)"
  blockers="$owners"
  if [ "$ALLOW_QUIESCED_COMFYUI" = "1" ] && [ -n "${owners// }" ]; then
    blockers=""
    for pid in $owners; do
      state="$(awk '/^State:/ {print $2}' "/proc/$pid/status" 2>/dev/null || true)"
      owner_uid="$(stat -c '%u' "/proc/$pid" 2>/dev/null || true)"
      cgroup="$(cat "/proc/$pid/cgroup" 2>/dev/null || true)"
      if [ "$owner_uid" = "$(id -u)" ] && { [ "$state" = "T" ] || [ "$state" = "t" ]; } && printf '%s\n' "$cgroup" | grep -qx '0::/system.slice/comfyui.service'; then
        continue
      fi
      blockers="$blockers $pid"
    done
  fi
  if (( vu <= MAX_INITIAL_VRAM )) && [ -z "${blockers// }" ]; then
    released=1
    break
  fi
  sleep 1
done
if (( released != 1 )); then
  echo "WVC=FAILED resource_release_timeout vram=$(vram_used)" >&2
  exit 82
fi

GPU_POST_RELEASE="$(count_gpu_errors)"
if (( GPU_POST_RELEASE != GPU_BASELINE )); then
  echo "WVC=FAILED gpu_error_after_release baseline=$GPU_BASELINE final=$GPU_POST_RELEASE" >&2
  exit 83
fi

# Deliberately no current alias, merge, runtime update or promotion.

{
  echo "training_rc=$TRAIN_RC"
  echo "gpu_error_baseline=$GPU_BASELINE"
  echo "gpu_error_final=$GPU_POST_RELEASE"
  echo "vram_after_release=$(vram_used)"
  echo "mem_available_kib_after=$(mem_available_kib)"
  echo "gpu_busy_after=$(gpu_busy)"
  echo "adapter_output=$OUT"
  echo "production_promotion=false"
} >"$EVIDENCE/postflight.txt"

echo "WVC_TRAINING=PASS"
echo "WVC_RUN_ID=$RUN_ID"
echo "WVC_ADAPTER=$OUT"
echo "WVC_LOG=$LOG"
echo "WVC_TELEMETRY=$TELEM"
echo "WVC_EVIDENCE=$EVIDENCE"
