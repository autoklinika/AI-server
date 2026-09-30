#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
DATA="${P5_DATA_ROOT:-/srv/ai-data/training/p5}"
MODEL="${P5_MODEL_DIR:-$DATA/models/Qwen3.8-27B-buffered-512m}"
ADAPTER_ALIAS="${P5_ADAPTER_DIR:-$DATA/adapters/electronics-foundation-v3/current}"
IMAGE="${P5_TRAIN_IMAGE:-ai-platform-p5-train:rocm7.2.1-v1}"
RUN_ID="${P5_5_RUN_ID:-p55-quality-v1-$(date -u +%Y%m%dT%H%M%SZ)}"
BATCH="${P5_5_BATCH_SIZE:-8}"
OUTDIR="$DATA/benchmarks/$RUN_ID"
RESULTS="$OUTDIR/results.jsonl"
LOG="$OUTDIR/generation.log"

REAL_ADAPTER="$(realpath "$ADAPTER_ALIAS")"
case "$REAL_ADAPTER" in
  "$DATA"/*) ;;
  *) echo "P5_5=BLOCKED adapter_outside_data_root=$REAL_ADAPTER" >&2; exit 41 ;;
esac
MODEL_REAL="$(realpath "$MODEL")"
case "$MODEL_REAL" in
  "$DATA"/*) ;;
  *) echo "P5_5=BLOCKED model_outside_data_root=$MODEL_REAL" >&2; exit 42 ;;
esac

test -f "$REAL_ADAPTER/adapter_config.json"
test -f "$MODEL_REAL/model.safetensors.index.json"
mkdir -p "$OUTDIR"

VRAM_USED="$(cat /sys/class/drm/card0/device/mem_info_vram_used 2>/dev/null || echo 0)"
if (( VRAM_USED > 2147483648 )); then
  echo "P5_5=BLOCKED gpu_vram_already_used=$VRAM_USED" >&2
  exit 43
fi
if ollama ps 2>/dev/null | tail -n +2 | grep -q .; then
  echo "P5_5=BLOCKED ollama_model_resident" >&2
  exit 44
fi

UIDN="$(id -u)"; GIDN="$(id -g)"
RGID="$(getent group render | cut -d: -f3)"
VGID="$(getent group video | cut -d: -f3)"
MODEL_IN="/p5${MODEL_REAL#$DATA}"
ADAPTER_IN="/p5${REAL_ADAPTER#$DATA}"

docker run --rm --name "p55-quality-$RUN_ID" \
  --memory=48g --memory-swap=48g \
  --user "$UIDN:$GIDN" --group-add "$RGID" --group-add "$VGID" \
  --device=/dev/kfd --device=/dev/dri --ipc=host --shm-size=8g \
  -e HOME=/p5/tmp/home -e HF_HOME=/p5/hf-cache \
  -v "$DATA:/p5" -v "$ROOT:/workspace:ro" "$IMAGE" \
  python3 /workspace/deploy/stage-p5/benchmark/run_quality_benchmark_v1.py \
    --model-dir "$MODEL_IN" --adapter-dir "$ADAPTER_IN" \
    --dataset /workspace/benchmarks/electronics_v3_quality_v1/cases.v1.jsonl \
    --output "/p5/benchmarks/$RUN_ID/results.jsonl" \
    --batch-size "$BATCH" --max-new-tokens 140 \
  2>&1 | tee "$LOG"

echo "P5_5_RUN_ID=$RUN_ID"
echo "P5_5_RESULTS=$RESULTS"
echo "P5_5_GENERATION_WRAPPER=PASS"
