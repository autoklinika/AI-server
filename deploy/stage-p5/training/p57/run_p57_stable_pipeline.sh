#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
DATA="${P5_DATA_ROOT:-/srv/ai-data/training/p5}"
MODEL="${P5_MODEL_DIR:-$DATA/models/Qwen3.8-27B-buffered-512m}"
PARENT="${P57_PARENT_ADAPTER:-$DATA/checkpoints/electronics-v4.1-contract-r1-20261001}"
IMAGE="${P5_TRAIN_IMAGE:-ai-platform-p5-train:rocm7.2.1-v1}"
RUN_ID="${P57_RUN_ID:-p57-seed1-$(date -u +%Y%m%dT%H%M%SZ)}"
SEED="${P57_SEED:-20261003}"
INTERVAL="${P57_CHECKPOINT_INTERVAL:-8}"
MAX_CKPT="${P57_MAX_CHECKPOINTS:-8}"
LR="${P57_LR:-0.00000075}"
MAXLEN="${P57_MAX_LENGTH:-512}"
RUNROOT="$DATA/p57/$RUN_ID"
CKPTROOT="$DATA/checkpoints/p57-$RUN_ID"
EVALROOT="$DATA/evals/$RUN_ID"
BENCHROOT="$DATA/benchmarks/$RUN_ID"
STATE="$RUNROOT/state.json"
mkdir -p "$RUNROOT" "$CKPTROOT" "$EVALROOT" "$BENCHROOT"
GIT_SHA="$(git -C "$ROOT" rev-parse HEAD)"

python3 "$ROOT/deploy/stage-p5/training/p57/prepare_p57_data.py" >"$RUNROOT/data.log"
python3 "$ROOT/deploy/stage-p5/training/p57/validate_p57.py" | tee "$RUNROOT/readiness.log"
grep -q '^P57_READINESS=PASS$' "$RUNROOT/readiness.log"
test -f "$PARENT/adapter_config.json"; test -f "$MODEL/model.safetensors.index.json"
ollama stop bge-m3 >/dev/null 2>&1 || true
sleep 2
if ollama ps 2>/dev/null | tail -n +2 | grep -q .; then echo "P57=BLOCKED ollama_resident" >&2; exit 43; fi
VRAM="$(cat /sys/class/drm/card0/device/mem_info_vram_used)"
if (( VRAM > 2147483648 )); then echo "P57=BLOCKED vram_used=$VRAM" >&2; exit 42; fi
MES_BASE="$(journalctl -b -k --no-pager | grep -c "MES ring buffer is full" || true)"
UIDN="$(id -u)"; GIDN="$(id -g)"; RGID="$(getent group render|cut -d: -f3)"; VGID="$(getent group video|cut -d: -f3)"

run_gpu() {
  local name="$1"; shift
  docker run --rm --name "$name" --memory=48g --memory-swap=48g --user "$UIDN:$GIDN" --group-add "$RGID" --group-add "$VGID" --device=/dev/kfd --device=/dev/dri --ipc=host --shm-size=8g -e HOME=/p5/tmp/home -e HF_HOME=/p5/hf-cache -e P5_GIT_SHA="$GIT_SHA" -v "$DATA:/p5" -v "$ROOT:/workspace:ro" "$IMAGE" "$@" &
  local dp=$!
  while kill -0 "$dp" 2>/dev/null; do
    sleep 2
    local mes
    mes="$(journalctl -b -k --no-pager | grep -c "MES ring buffer is full" || true)"
    if (( mes > MES_BASE )); then
      docker kill "$name" >/dev/null 2>&1 || true; wait "$dp" || true
      echo "P57=FAIL mes_increment baseline=$MES_BASE current=$mes" >&2; exit 89
    fi
  done
  wait "$dp"
}
echo "P57_MARK=BASELINE_REGRESSION"
run_gpu "p57-base-reg-$RUN_ID" python3 /workspace/deploy/stage-p5/training/electronics_v4/eval_multi_holdout_v4.py   --model-dir /p5/models/Qwen3.8-27B-buffered-512m   --adapter-dir "${PARENT/$DATA//p5}"   --dataset reg=/workspace/deploy/stage-p5/training/p57/p57_regression_slice_v1.jsonl   --output-dir "/p5/evals/$RUN_ID/baseline_reg"

python3 "$ROOT/deploy/stage-p5/benchmark/score_quality_benchmark_v3.py"   --dataset "$ROOT/benchmarks/electronics_v3_quality_v1/cases.v1.jsonl"   --results "$DATA/benchmarks/p561-contract-r1-20261001-p55/results.jsonl"   --output "$BENCHROOT/legacy_parent_v3.json" | tee "$RUNROOT/legacy_parent_score.log"
ollama stop bge-m3 >/dev/null 2>&1 || true

CURRENT="$PARENT"
for ((i=1;i<=MAX_CKPT;i++)); do
  TOTAL=$((i*INTERVAL)); START=$(((i-1)*INTERVAL)); TAG="$(printf '%03d' "$TOTAL")"
  CKPT="$CKPTROOT/step-$TAG"
  echo "P57_MARK=TRAIN_CHECKPOINT index=$i total_steps=$TOTAL parent=$CURRENT"
  run_gpu "p57-train-$i-$RUN_ID" python3 /workspace/deploy/stage-p5/training/microtrain_lora_bf16.py     --model-dir /p5/models/Qwen3.8-27B-buffered-512m     --dataset /workspace/deploy/stage-p5/training/p57/p57_balanced_train.jsonl     --output-dir "${CKPT/$DATA//p5}" --steps "$INTERVAL" --max-length "$MAXLEN"     --seed "$((SEED+i))" --lora-r 8 --lr "$LR"     --adapter-dir "${CURRENT/$DATA//p5}" --start-index "$START"     --purpose "P5.7 stable segmented training; checkpoint=$TOTAL; DEV-selected; FINAL-isolated; never merged into Qwen base"     2>&1 | tee "$RUNROOT/train-step-$TAG.log"

  run_gpu "p57-reg-$i-$RUN_ID" python3 /workspace/deploy/stage-p5/training/electronics_v4/eval_multi_holdout_v4.py     --model-dir /p5/models/Qwen3.8-27B-buffered-512m --adapter-dir "${CKPT/$DATA//p5}"     --dataset reg=/workspace/deploy/stage-p5/training/p57/p57_regression_slice_v1.jsonl     --output-dir "/p5/evals/$RUN_ID/step-$TAG-reg"

  run_gpu "p57-dev-$i-$RUN_ID" python3 /workspace/deploy/stage-p5/benchmark/run_quality_benchmark_v2.py     --model-dir /p5/models/Qwen3.8-27B-buffered-512m --adapter-dir "${CKPT/$DATA//p5}"     --dataset /workspace/deploy/stage-p5/training/p57/p57_mini_dev_v1.jsonl     --output "/p5/benchmarks/$RUN_ID/step-$TAG-mini/results.jsonl" --batch-size 7 --max-new-tokens 140

  python3 "$ROOT/deploy/stage-p5/benchmark/score_quality_benchmark_v3.py"     --dataset "$ROOT/deploy/stage-p5/training/p57/p57_mini_dev_v1.jsonl"     --results "$BENCHROOT/step-$TAG-mini/results.jsonl"     --output "$BENCHROOT/step-$TAG-mini/score_v3.json" | tee "$RUNROOT/score-step-$TAG.log"
  ollama stop bge-m3 >/dev/null 2>&1 || true

  python3 "$ROOT/deploy/stage-p5/training/p57/checkpoint_gate.py"     --baseline-reg "$EVALROOT/baseline_reg/reg.json"     --checkpoint-reg "$EVALROOT/step-$TAG-reg/reg.json"     --quality "$BENCHROOT/step-$TAG-mini/score_v3.json"     --checkpoint "$CKPT" --index "$i" --state "$STATE" --max-regression 0.02 --patience 2     | tee "$RUNROOT/gate-step-$TAG.log"
  CURRENT="$CKPT"
  if grep -q '^P57_STOP=1$' "$RUNROOT/gate-step-$TAG.log"; then
    echo "P57_MARK=EARLY_STOP checkpoint=$TAG"
    break
  fi
done

BEST="$(python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); print(d.get("best_checkpoint") or "")' "$STATE")"
if [[ -z "$BEST" || ! -f "$BEST/adapter_config.json" ]]; then echo "P57=FAIL no_eligible_checkpoint" >&2; exit 51; fi
echo "$BEST" > "$RUNROOT/best_checkpoint.txt"
echo "P57_MARK=BEST_CHECKPOINT path=$BEST"
run_gpu "p57-full-dev-$RUN_ID" python3 /workspace/deploy/stage-p5/benchmark/run_quality_benchmark_v2.py   --model-dir /p5/models/Qwen3.8-27B-buffered-512m --adapter-dir "${BEST/$DATA//p5}"   --dataset /workspace/deploy/stage-p5/training/p57/p57_dev_v1.jsonl   --output "/p5/benchmarks/$RUN_ID/full-dev/results.jsonl" --batch-size 7 --max-new-tokens 140
python3 "$ROOT/deploy/stage-p5/benchmark/score_quality_benchmark_v3.py"   --dataset "$ROOT/deploy/stage-p5/training/p57/p57_dev_v1.jsonl"   --results "$BENCHROOT/full-dev/results.jsonl" --output "$BENCHROOT/full-dev/score_v3.json"   | tee "$RUNROOT/full-dev-score.log"
ollama stop bge-m3 >/dev/null 2>&1 || true

run_gpu "p57-full-reg-$RUN_ID" python3 /workspace/deploy/stage-p5/training/electronics_v4/eval_multi_holdout_v4.py   --model-dir /p5/models/Qwen3.8-27B-buffered-512m --adapter-dir "${BEST/$DATA//p5}"   --dataset v1=/workspace/deploy/stage-p5/training/electronics/electronics_foundation_holdout_v1.jsonl   --dataset v2=/workspace/deploy/stage-p5/training/electronics_v2/electronics_foundation_v2_holdout.jsonl   --dataset v3=/workspace/deploy/stage-p5/training/electronics_v3/electronics_foundation_v3_holdout.jsonl   --dataset v4=/workspace/deploy/stage-p5/training/electronics_v4/discriminating_measurement_v4_holdout.jsonl   --output-dir "/p5/evals/$RUN_ID/full_regression"

run_gpu "p57-legacy-$RUN_ID" python3 /workspace/deploy/stage-p5/benchmark/run_quality_benchmark_v2.py   --model-dir /p5/models/Qwen3.8-27B-buffered-512m --adapter-dir "${BEST/$DATA//p5}"   --dataset /workspace/benchmarks/electronics_v3_quality_v1/cases.v1.jsonl   --output "/p5/benchmarks/$RUN_ID/legacy-p55/results.jsonl" --batch-size 7 --max-new-tokens 140
python3 "$ROOT/deploy/stage-p5/benchmark/score_quality_benchmark_v3.py"   --dataset "$ROOT/benchmarks/electronics_v3_quality_v1/cases.v1.jsonl"   --results "$BENCHROOT/legacy-p55/results.jsonl" --output "$BENCHROOT/legacy-p55/score_v3.json"   | tee "$RUNROOT/legacy-candidate-score.log"
ollama stop bge-m3 >/dev/null 2>&1 || true

# FINAL is touched for the first time only after checkpoint selection and all regression work.
echo "P57_MARK=FINAL_OPEN sha=$(sha256sum "$ROOT/deploy/stage-p5/training/p57/p57_final_v1.jsonl" | awk '{print $1}')"
run_gpu "p57-final-$RUN_ID" python3 /workspace/deploy/stage-p5/benchmark/run_quality_benchmark_v2.py   --model-dir /p5/models/Qwen3.8-27B-buffered-512m --adapter-dir "${BEST/$DATA//p5}"   --dataset /workspace/deploy/stage-p5/training/p57/p57_final_v1.jsonl   --output "/p5/benchmarks/$RUN_ID/final/results.jsonl" --batch-size 7 --max-new-tokens 140
python3 "$ROOT/deploy/stage-p5/benchmark/score_quality_benchmark_v3.py"   --dataset "$ROOT/deploy/stage-p5/training/p57/p57_final_v1.jsonl"   --results "$BENCHROOT/final/results.jsonl" --output "$BENCHROOT/final/score_v3.json"   | tee "$RUNROOT/final-score.log"
ollama stop bge-m3 >/dev/null 2>&1 || true
set +e
python3 "$ROOT/deploy/stage-p5/training/p57/final_gate.py"   --dev-quality "$BENCHROOT/full-dev/score_v3.json" --final-quality "$BENCHROOT/final/score_v3.json"   --legacy-parent "$BENCHROOT/legacy_parent_v3.json" --legacy-candidate "$BENCHROOT/legacy-p55/score_v3.json"   --parent-v1 "$DATA/evals/p561-contract-r1-20261001/tuned/v1.json" --candidate-v1 "$EVALROOT/full_regression/v1.json"   --parent-v2 "$DATA/evals/p561-contract-r1-20261001/tuned/v2.json" --candidate-v2 "$EVALROOT/full_regression/v2.json"   --parent-v3 "$DATA/evals/p561-contract-r1-20261001/tuned/v3.json" --candidate-v3 "$EVALROOT/full_regression/v3.json"   --parent-v4 "$DATA/evals/p561-contract-r1-20261001/tuned/v4.json" --candidate-v4 "$EVALROOT/full_regression/v4.json"   --candidate "$BEST" --run-id "$RUN_ID" --output "$RUNROOT/final_gate.json"   | tee "$RUNROOT/final-gate.log"
RC=${PIPESTATUS[0]}
set -e
if (( RC==0 )); then echo "P57_PIPELINE=QUALIFIED_RUN"; else echo "P57_PIPELINE=FAIL"; fi
echo "P57_RUN_ID=$RUN_ID"
echo "P57_BEST_CHECKPOINT=$BEST"
echo "P57_RUNROOT=$RUNROOT"
exit "$RC"
