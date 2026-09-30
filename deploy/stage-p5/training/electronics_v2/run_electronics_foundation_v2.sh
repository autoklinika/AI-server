#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
DATA="${P5_DATA_ROOT:-/srv/ai-data/training/p5}"
MODEL="${P5_MODEL_DIR:-$DATA/models/Qwen3.8-27B-buffered-512m}"
DATASET="$ROOT/deploy/stage-p5/training/electronics_v2/electronics_foundation_v2_train.jsonl"
BASE_ADAPTER="${P5_ELECTRONICS_V2_BASE_ADAPTER:-$DATA/adapters/electronics-foundation-v1/current}"
IMAGE="${P5_TRAIN_IMAGE:-ai-platform-p5-train:rocm7.2.1-v1}"
STEPS="${P5_ELECTRONICS_V2_STEPS:-40}"
MAX_LENGTH="${P5_ELECTRONICS_V2_MAX_LENGTH:-448}"
LORA_R="${P5_ELECTRONICS_V2_LORA_R:-8}"
LR="${P5_ELECTRONICS_V2_LR:-0.00005}"
CGROUP_MEMORY="${P5_CGROUP_MEMORY:-48g}"
CGROUP_SWAP="${P5_CGROUP_SWAP:-$CGROUP_MEMORY}"
MIN_HOST_AVAILABLE_KIB="${P5_MIN_HOST_AVAILABLE_KIB:-8388608}"
RUN_ID="${P5_RUN_ID:-electronics-v2-r1-$(date -u +%Y%m%dT%H%M%SZ)}"
CONTAINER_NAME="p5-electronics-v2-$RUN_ID"
OUT="$DATA/checkpoints/electronics-v2-$RUN_ID"
LOG="$DATA/logs/electronics-v2-$RUN_ID.log"
TELEM="$DATA/logs/electronics-v2-$RUN_ID-host.csv"
GIT_SHA="$(git -C "$ROOT" rev-parse HEAD)"

python3 "$ROOT/deploy/stage-p5/training/electronics_v2/prepare_electronics_foundation_v2.py" >/tmp/p53-data.txt
grep -q '^P5_3_ELECTRONICS_V2_DATASET_GATE=PASS$' /tmp/p53-data.txt
test -f "$MODEL/model.safetensors.index.json"
test -f "$BASE_ADAPTER/adapter_config.json"
BASE_ADAPTER_REAL="$(realpath "$BASE_ADAPTER")"
test -f "$BASE_ADAPTER_REAL/adapter_config.json"
mkdir -p "$OUT" "$(dirname "$LOG")"

VRAM_USED="$(cat /sys/class/drm/card0/device/mem_info_vram_used)"
if (( VRAM_USED > 2147483648 )); then
  echo "P5_3_ELECTRONICS=BLOCKED gpu_vram_already_used=$VRAM_USED" >&2; exit 42
fi
if ollama ps 2>/dev/null | tail -n +2 | grep -q .; then
  echo "P5_3_ELECTRONICS=BLOCKED ollama_model_resident" >&2; ollama ps >&2; exit 43
fi

printf "timestamp,vram_used_bytes,mem_available_kib\n" > "$TELEM"
(
 while true; do
  ts="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  vu="$(cat /sys/class/drm/card0/device/mem_info_vram_used 2>/dev/null || echo 0)"
  ma="$(awk '/MemAvailable:/ {print $2}' /proc/meminfo)"
  printf "%s,%s,%s\n" "$ts" "$vu" "$ma" >> "$TELEM"
  if (( ma < MIN_HOST_AVAILABLE_KIB )); then
    echo "P5_HOST_WATCHDOG=TRIGGERED mem_available_kib=$ma threshold_kib=$MIN_HOST_AVAILABLE_KIB" >&2
    docker kill "$CONTAINER_NAME" >/dev/null 2>&1 || true; exit 88
  fi
  sleep 1
 done
) &
MON_PID=$!
trap 'kill "$MON_PID" 2>/dev/null || true' EXIT

UIDN="$(id -u)"; GIDN="$(id -g)"
RGID="$(getent group render | cut -d: -f3)"; VGID="$(getent group video | cut -d: -f3)"

docker run --rm --name "$CONTAINER_NAME"  --memory="$CGROUP_MEMORY" --memory-swap="$CGROUP_SWAP"  --user "$UIDN:$GIDN" --group-add "$RGID" --group-add "$VGID"  --device=/dev/kfd --device=/dev/dri --ipc=host --shm-size=8g  -e HOME=/p5/tmp/home -e HF_HOME=/p5/hf-cache -e P5_GIT_SHA="$GIT_SHA"  -v "$DATA:/p5" -v "$ROOT:/workspace:ro" "$IMAGE"  python3 /workspace/deploy/stage-p5/training/microtrain_lora_bf16.py  --model-dir "${MODEL/$DATA//p5}"  --dataset /workspace/deploy/stage-p5/training/electronics_v2/electronics_foundation_v2_train.jsonl  --output-dir "/p5/checkpoints/electronics-v2-$RUN_ID"  --steps "$STEPS" --max-length "$MAX_LENGTH" --seed 20260930  --lora-r "$LORA_R" --lr "$LR" --shuffle  --adapter-dir "${BASE_ADAPTER_REAL/$DATA//p5}" --start-index 0  --purpose "P5.3 electronics-foundation-v2 expansion from selected electronics-foundation-v1 R1; non-deployable until dual-holdout acceptance"  2>&1 | tee "$LOG"

kill "$MON_PID" 2>/dev/null || true
trap - EXIT
echo "P5_3_RUN_ID=$RUN_ID"
echo "P5_3_OUTPUT=$OUT"
echo "P5_3_LOG=$LOG"
echo "P5_3_TELEMETRY=$TELEM"
