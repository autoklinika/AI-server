#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
DATA="${P5_DATA_ROOT:-/srv/ai-data/training/p5}"
MODEL="${P5_MODEL_DIR:-$DATA/models/Qwen3.8-27B-buffered-512m}"
DATASET="$ROOT/deploy/stage-p5/training/electronics_v4/discriminating_measurement_v4_replay_train.jsonl"
BASE_ADAPTER="${P5_ELECTRONICS_V4_BASE_ADAPTER:-$DATA/adapters/electronics-foundation-v3/current}"
IMAGE="${P5_TRAIN_IMAGE:-ai-platform-p5-train:rocm7.2.1-v1}"
STEPS="${P5_ELECTRONICS_V4_STEPS:-65}"
MAX_LENGTH="${P5_ELECTRONICS_V4_MAX_LENGTH:-1280}"
LORA_R="${P5_ELECTRONICS_V4_LORA_R:-8}"
LR="${P5_ELECTRONICS_V4_LR:-0.00001}"
CGROUP_MEMORY="${P5_CGROUP_MEMORY:-48g}"
CGROUP_SWAP="${P5_CGROUP_SWAP:-$CGROUP_MEMORY}"
MIN_HOST_AVAILABLE_KIB="${P5_MIN_HOST_AVAILABLE_KIB:-8388608}"
RUN_ID="${P5_RUN_ID:-electronics-v4-measurement-r1-$(date -u +%Y%m%dT%H%M%SZ)}"
CONTAINER_NAME="p5-electronics-v4-$RUN_ID"
OUT="$DATA/checkpoints/electronics-v4-$RUN_ID"
LOG="$DATA/logs/electronics-v4-$RUN_ID.log"
TELEM="$DATA/logs/electronics-v4-$RUN_ID-host.csv"
GIT_SHA="$(git -C "$ROOT" rev-parse HEAD)"

python3 "$ROOT/deploy/stage-p5/training/electronics_v4/prepare_discriminating_measurement_v4.py" >/tmp/p56-data.txt
grep -q '^P5_6_TARGET_DATASET=PASS$' /tmp/p56-data.txt
python3 "$ROOT/deploy/stage-p5/training/electronics_v4/prepare_v4_replay.py" >/tmp/p56-replay.txt
grep -q '^P5_6_REPLAY_DATASET=PASS$' /tmp/p56-replay.txt
python3 "$ROOT/deploy/stage-p5/training/electronics_v4/validate_discriminating_measurement_v4.py" >/tmp/p56-ready.txt
grep -q '^P5_6_READINESS=PASS$' /tmp/p56-ready.txt

TRAIN_SEED="$(python3 - <<'PY'
import json
print(json.load(open("deploy/stage-p5/training/electronics_v4/discriminating_measurement_v4_replay.manifest.json"))["trainer_shuffle_seed"])
PY
)"

test -f "$MODEL/model.safetensors.index.json"
test -f "$BASE_ADAPTER/adapter_config.json"
BASE_ADAPTER_REAL="$(realpath "$BASE_ADAPTER")"
test -f "$BASE_ADAPTER_REAL/adapter_config.json"
mkdir -p "$OUT" "$(dirname "$LOG")"

VRAM_USED="$(cat /sys/class/drm/card0/device/mem_info_vram_used)"
if (( VRAM_USED > 2147483648 )); then
  echo "P5_6_ELECTRONICS=BLOCKED gpu_vram_already_used=$VRAM_USED" >&2
  exit 42
fi
if ollama ps 2>/dev/null | tail -n +2 | grep -q .; then
  echo "P5_6_ELECTRONICS=BLOCKED ollama_model_resident" >&2
  ollama ps >&2
  exit 43
fi

printf "timestamp,vram_used_bytes,mem_available_kib,mes_count\n" > "$TELEM"
MES_BASELINE="$(journalctl -b -k --no-pager 2>/dev/null | grep -c "MES ring buffer is full" || true)"
(
  tick=0
  mes="$MES_BASELINE"
  while true; do
    ts="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    vu="$(cat /sys/class/drm/card0/device/mem_info_vram_used 2>/dev/null || echo 0)"
    ma="$(awk '/MemAvailable:/ {print $2}' /proc/meminfo)"
    if (( tick % 5 == 0 )); then
      mes="$(journalctl -b -k --no-pager 2>/dev/null | grep -c "MES ring buffer is full" || true)"
    fi
    printf "%s,%s,%s,%s\n" "$ts" "$vu" "$ma" "$mes" >> "$TELEM"
    if (( ma < MIN_HOST_AVAILABLE_KIB )); then
      echo "P5_HOST_WATCHDOG=TRIGGERED mem_available_kib=$ma threshold_kib=$MIN_HOST_AVAILABLE_KIB" >&2
      docker kill "$CONTAINER_NAME" >/dev/null 2>&1 || true
      exit 88
    fi
    if (( mes > MES_BASELINE )); then
      echo "P5_MES_WATCHDOG=TRIGGERED baseline=$MES_BASELINE current=$mes" >&2
      docker kill "$CONTAINER_NAME" >/dev/null 2>&1 || true
      exit 89
    fi
    tick=$((tick+1))
    sleep 1
  done
) &
MON_PID=$!
trap 'kill "$MON_PID" 2>/dev/null || true' EXIT

UIDN="$(id -u)"; GIDN="$(id -g)"
RGID="$(getent group render | cut -d: -f3)"
VGID="$(getent group video | cut -d: -f3)"

docker run --rm --name "$CONTAINER_NAME" \
  --memory="$CGROUP_MEMORY" --memory-swap="$CGROUP_SWAP" \
  --user "$UIDN:$GIDN" --group-add "$RGID" --group-add "$VGID" \
  --device=/dev/kfd --device=/dev/dri --ipc=host --shm-size=8g \
  -e HOME=/p5/tmp/home -e HF_HOME=/p5/hf-cache -e P5_GIT_SHA="$GIT_SHA" \
  -v "$DATA:/p5" -v "$ROOT:/workspace:ro" "$IMAGE" \
  python3 /workspace/deploy/stage-p5/training/microtrain_lora_bf16.py \
    --model-dir "${MODEL/$DATA//p5}" \
    --dataset /workspace/deploy/stage-p5/training/electronics_v4/discriminating_measurement_v4_replay_train.jsonl \
    --output-dir "/p5/checkpoints/electronics-v4-$RUN_ID" \
    --steps "$STEPS" --max-length "$MAX_LENGTH" --seed "$TRAIN_SEED" \
    --lora-r "$LORA_R" --lr "$LR" --shuffle \
    --adapter-dir "${BASE_ADAPTER_REAL/$DATA//p5}" --start-index 0 \
    --purpose "P5.6 discriminating-measurement specialization; 300 contrastive microcases plus v3/v2/v1 replay; parent electronics-foundation-v3; never merged into Qwen base; non-deployable until P5.5 frozen re-gate and holdout regression checks" \
    2>&1 | tee "$LOG"

kill "$MON_PID" 2>/dev/null || true
trap - EXIT
echo "P5_6_RUN_ID=$RUN_ID"
echo "P5_6_OUTPUT=$OUT"
echo "P5_6_LOG=$LOG"
echo "P5_6_TELEMETRY=$TELEM"
