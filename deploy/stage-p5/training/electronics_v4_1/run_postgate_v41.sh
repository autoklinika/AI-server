#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
DATA="${P5_DATA_ROOT:-/srv/ai-data/training/p5}"
MODEL="$DATA/models/Qwen3.8-27B-buffered-512m"
PARENT="${P5_ELECTRONICS_V41_PARENT:-$DATA/checkpoints/electronics-v4-measurement-r3-20261001}"
TUNED="${P5_ELECTRONICS_V41_ADAPTER:-$DATA/checkpoints/electronics-v4.1-contract-r1-20261001}"
IMAGE="${P5_TRAIN_IMAGE:-ai-platform-p5-train:rocm7.2.1-v1}"
RUN="${P5_GATE_RUN_ID:-p561-contract-r1-20261001}"
EVAL="$DATA/evals/$RUN"
BENCH="$DATA/benchmarks/$RUN-p55"
mkdir -p "$EVAL" "$BENCH"

if docker ps --format '{{.Names}}' | grep -q '^p5-electronics-v41-'; then
  echo "P5_6_1_POSTGATE=BLOCKED training_active" >&2; exit 42
fi
ollama stop bge-m3 >/dev/null 2>&1 || true
BASE_MES="$(journalctl -b -k --no-pager | grep -c "MES ring buffer is full" || true)"
UIDN="$(id -u)"; GIDN="$(id -g)"; RGID="$(getent group render|cut -d: -f3)"; VGID="$(getent group video|cut -d: -f3)"

run_gpu() {
  local name="$1"; shift
  docker run --rm --name "$name" --memory=48g --memory-swap=48g --user "$UIDN:$GIDN" --group-add "$RGID" --group-add "$VGID" --device=/dev/kfd --device=/dev/dri --ipc=host --shm-size=8g -e HOME=/p5/tmp/home -e HF_HOME=/p5/hf-cache -v "$DATA:/p5" -v "$ROOT:/workspace:ro" "$IMAGE" "$@" &
  local dp=$!
  while kill -0 "$dp" 2>/dev/null; do
    sleep 2
    local cur
    cur="$(journalctl -b -k --no-pager | grep -c "MES ring buffer is full" || true)"
    if (( cur > BASE_MES )); then
      docker kill "$name" >/dev/null 2>&1 || true
      wait "$dp" || true
      echo "P5_6_1_POSTGATE=FAIL mes_increment" >&2
      exit 89
    fi
  done
  wait "$dp"
}

run_gpu "p561-parent-v41-$RUN" python3 /workspace/deploy/stage-p5/training/electronics_v4/eval_multi_holdout_v4.py   --model-dir /p5/models/Qwen3.8-27B-buffered-512m   --adapter-dir "${PARENT/$DATA//p5}"   --dataset v41=/workspace/deploy/stage-p5/training/electronics_v4_1/contract_aligned_v41_holdout.jsonl   --output-dir "/p5/evals/$RUN/parent"

run_gpu "p561-tuned-holdouts-$RUN" python3 /workspace/deploy/stage-p5/training/electronics_v4/eval_multi_holdout_v4.py   --model-dir /p5/models/Qwen3.8-27B-buffered-512m   --adapter-dir "${TUNED/$DATA//p5}"   --dataset v1=/workspace/deploy/stage-p5/training/electronics/electronics_foundation_holdout_v1.jsonl   --dataset v2=/workspace/deploy/stage-p5/training/electronics_v2/electronics_foundation_v2_holdout.jsonl   --dataset v3=/workspace/deploy/stage-p5/training/electronics_v3/electronics_foundation_v3_holdout.jsonl   --dataset v4=/workspace/deploy/stage-p5/training/electronics_v4/discriminating_measurement_v4_holdout.jsonl   --dataset v41=/workspace/deploy/stage-p5/training/electronics_v4_1/contract_aligned_v41_holdout.jsonl   --output-dir "/p5/evals/$RUN/tuned"

run_gpu "p561-p55-$RUN" python3 /workspace/deploy/stage-p5/benchmark/run_quality_benchmark_v1.py   --model-dir /p5/models/Qwen3.8-27B-buffered-512m   --adapter-dir "${TUNED/$DATA//p5}"   --dataset /workspace/benchmarks/electronics_v3_quality_v1/cases.v1.jsonl   --output "/p5/benchmarks/$RUN-p55/results.jsonl" --batch-size 8 --max-new-tokens 140

python3 "$ROOT/deploy/stage-p5/benchmark/score_quality_benchmark_v1.py"   --results "$BENCH/results.jsonl" --output "$BENCH/quality_score_v1.json"
python3 "$ROOT/deploy/stage-p5/benchmark/score_quality_benchmark_v2.py"   --results "$BENCH/results.jsonl" --output "$BENCH/quality_score_v2.json"

python3 "$ROOT/deploy/stage-p5/training/electronics_v4_1/final_gate_v41.py"   --parent-v41 "$EVAL/parent/v41.json" --tuned-v41 "$EVAL/tuned/v41.json"   --parent-v1 "$DATA/evals/p56-r3-tuned/v1.json" --tuned-v1 "$EVAL/tuned/v1.json"   --parent-v2 "$DATA/evals/p56-r3-tuned/v2.json" --tuned-v2 "$EVAL/tuned/v2.json"   --parent-v3 "$DATA/evals/p56-r3-tuned/v3.json" --tuned-v3 "$EVAL/tuned/v3.json"   --parent-v4 "$DATA/evals/p56-r3-tuned/v4.json" --tuned-v4 "$EVAL/tuned/v4.json"   --quality-v1 "$BENCH/quality_score_v1.json" --quality-v2 "$BENCH/quality_score_v2.json"   --output "$EVAL/final_gate.json"
echo "P5_6_1_POSTGATE=PASS"
