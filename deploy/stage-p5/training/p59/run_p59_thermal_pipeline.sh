#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
DATA="${P5_DATA_ROOT:-/srv/ai-data/training/p5}"
MODEL="${P5_MODEL_DIR:-$DATA/models/Qwen3.8-27B-buffered-512m}"
PARENT="${P59_PARENT_ADAPTER:-$DATA/checkpoints/p58-p58-seed1-20261001/step-008}"
IMAGE="${P5_TRAIN_IMAGE:-ai-platform-p5-train:rocm7.2.1-v1}"
P58_RUN="${P58_PARENT_RUN:-p58-seed1-20261001}"
RUN_ID="${P59_RUN_ID:-p59-seed1-$(date -u +%Y%m%dT%H%M%SZ)}"
SEED="${P59_SEED:-20261019}"
INTERVAL="${P59_CHECKPOINT_INTERVAL:-8}"
MAX_CKPT="${P59_MAX_CHECKPOINTS:-8}"
LR="${P59_LR:-0.0000003}"
MAXLEN="${P59_MAX_LENGTH:-512}"

RUNROOT="$DATA/p59/$RUN_ID"
CKPTROOT="$DATA/checkpoints/p59-$RUN_ID"
EVALROOT="$DATA/evals/$RUN_ID"
BENCHROOT="$DATA/benchmarks/$RUN_ID"
P58_BENCH="$DATA/benchmarks/$P58_RUN"
P58_EVAL="$DATA/evals/$P58_RUN"
STATE="$RUNROOT/state.json"
mkdir -p "$RUNROOT" "$CKPTROOT" "$EVALROOT" "$BENCHROOT"
GIT_SHA="$(git -C "$ROOT" rev-parse HEAD)"
python3 "$ROOT/deploy/stage-p5/training/p59/prepare_p59_data.py" >"$RUNROOT/data.log"
python3 "$ROOT/deploy/stage-p5/training/p59/validate_p59.py" | tee "$RUNROOT/readiness.log"
grep -q '^P59_READINESS=PASS$' "$RUNROOT/readiness.log"

test -f "$PARENT/adapter_config.json"
test -f "$MODEL/model.safetensors.index.json"
test -f "$P58_BENCH/p57-final-regression/results.jsonl"
test -f "$P58_BENCH/p55-regression/results.jsonl"
for v in v1 v2 v3 v4; do test -f "$P58_EVAL/full_regression/$v.json"; done

# P58-FINAL must still be pristine before P5.9.
if [[ -s "$P58_BENCH/final/results.jsonl" ]]; then
  echo "P59=BLOCKED p58_final_already_open" >&2
  exit 61
fi

ollama stop bge-m3 >/dev/null 2>&1 || true
sleep 2
if ollama ps 2>/dev/null | tail -n +2 | grep -q .; then
  echo "P59=BLOCKED ollama_resident" >&2
  exit 43
fi
VRAM="$(cat /sys/class/drm/card0/device/mem_info_vram_used)"
if (( VRAM > 2147483648 )); then
  echo "P59=BLOCKED vram_used=$VRAM" >&2
  exit 42
fi
MES_BASE="$(journalctl -b -k --no-pager | grep -c "MES ring buffer is full" || true)"
UIDN="$(id -u)"; GIDN="$(id -g)"
RGID="$(getent group render|cut -d: -f3)"
VGID="$(getent group video|cut -d: -f3)"

run_gpu() {
  local name="$1"; shift
  if ollama ps 2>/dev/null | tail -n +2 | grep -q .; then
    echo "P59=BLOCKED ollama_resident_before_$name" >&2
    exit 44
  fi
  docker run --rm --name "$name" --memory=48g --memory-swap=48g     --user "$UIDN:$GIDN" --group-add "$RGID" --group-add "$VGID"     --device=/dev/kfd --device=/dev/dri --ipc=host --shm-size=8g     -e HOME=/p5/tmp/home -e HF_HOME=/p5/hf-cache -e P5_GIT_SHA="$GIT_SHA"     -v "$DATA:/p5" -v "$ROOT:/workspace:ro" "$IMAGE" "$@" &
  local dp=$!
  while kill -0 "$dp" 2>/dev/null; do
    sleep 2
    local mes
    mes="$(journalctl -b -k --no-pager | grep -c "MES ring buffer is full" || true)"
    if (( mes > MES_BASE )); then
      docker kill "$name" >/dev/null 2>&1 || true
      wait "$dp" || true
      echo "P59=FAIL mes_increment baseline=$MES_BASE current=$mes" >&2
      exit 89
    fi
  done
  wait "$dp"
}
score_v4() {
  local dataset="$1" results="$2" output="$3" log="$4"
  python3 "$ROOT/deploy/stage-p5/benchmark/score_quality_benchmark_v4.py"     --dataset "$dataset" --results "$results" --output "$output" | tee "$log"
  ollama stop bge-m3 >/dev/null 2>&1 || true
  sleep 2
}

echo "P59_MARK=BASELINE_REGRESSION"
run_gpu "p59-base-reg-$RUN_ID"   python3 /workspace/deploy/stage-p5/training/electronics_v4/eval_multi_holdout_v4.py   --model-dir /p5/models/Qwen3.8-27B-buffered-512m   --adapter-dir "${PARENT/$DATA//p5}"   --dataset reg=/workspace/deploy/stage-p5/training/p57/p57_regression_slice_v1.jsonl   --output-dir "/p5/evals/$RUN_ID/baseline_reg"

echo "P59_MARK=BASELINE_MINI_DEV"
run_gpu "p59-base-mini-$RUN_ID"   python3 /workspace/deploy/stage-p5/benchmark/run_quality_benchmark_v2.py   --model-dir /p5/models/Qwen3.8-27B-buffered-512m   --adapter-dir "${PARENT/$DATA//p5}"   --dataset /workspace/deploy/stage-p5/training/p59/p59_thermal_mini_dev_v1.jsonl   --output "/p5/benchmarks/$RUN_ID/baseline-mini/results.jsonl"   --batch-size 7 --max-new-tokens 140
score_v4 "$ROOT/deploy/stage-p5/training/p59/p59_thermal_mini_dev_v1.jsonl"   "$BENCHROOT/baseline-mini/results.jsonl"   "$BENCHROOT/baseline-mini/score_v4.json"   "$RUNROOT/baseline-mini-score.log"

CURRENT="$PARENT"
for ((i=1;i<=MAX_CKPT;i++)); do
  TOTAL=$((i*INTERVAL))
  START=$(((i-1)*INTERVAL))
  TAG="$(printf '%03d' "$TOTAL")"
  CKPT="$CKPTROOT/step-$TAG"

  echo "P59_MARK=TRAIN_CHECKPOINT index=$i total_steps=$TOTAL parent=$CURRENT"
  run_gpu "p59-train-$i-$RUN_ID"     python3 /workspace/deploy/stage-p5/training/microtrain_lora_bf16.py     --model-dir /p5/models/Qwen3.8-27B-buffered-512m     --dataset /workspace/deploy/stage-p5/training/p59/p59_thermal_train.jsonl     --output-dir "${CKPT/$DATA//p5}"     --steps "$INTERVAL" --max-length "$MAXLEN"     --seed "$((SEED+i))" --lora-r 8 --lr "$LR"     --adapter-dir "${CURRENT/$DATA//p5}" --start-index "$START"     --purpose "P5.9 thermal causal prediction; P58-FINAL sealed; never merged into Qwen base"     2>&1 | tee "$RUNROOT/train-step-$TAG.log"
  run_gpu "p59-reg-$i-$RUN_ID"     python3 /workspace/deploy/stage-p5/training/electronics_v4/eval_multi_holdout_v4.py     --model-dir /p5/models/Qwen3.8-27B-buffered-512m     --adapter-dir "${CKPT/$DATA//p5}"     --dataset reg=/workspace/deploy/stage-p5/training/p57/p57_regression_slice_v1.jsonl     --output-dir "/p5/evals/$RUN_ID/step-$TAG-reg"

  run_gpu "p59-mini-$i-$RUN_ID"     python3 /workspace/deploy/stage-p5/benchmark/run_quality_benchmark_v2.py     --model-dir /p5/models/Qwen3.8-27B-buffered-512m     --adapter-dir "${CKPT/$DATA//p5}"     --dataset /workspace/deploy/stage-p5/training/p59/p59_thermal_mini_dev_v1.jsonl     --output "/p5/benchmarks/$RUN_ID/step-$TAG-mini/results.jsonl"     --batch-size 7 --max-new-tokens 140

  score_v4 "$ROOT/deploy/stage-p5/training/p59/p59_thermal_mini_dev_v1.jsonl"     "$BENCHROOT/step-$TAG-mini/results.jsonl"     "$BENCHROOT/step-$TAG-mini/score_v4.json"     "$RUNROOT/score-step-$TAG.log"
  python3 "$ROOT/deploy/stage-p5/training/p59/checkpoint_gate_p59.py"     --baseline-reg "$EVALROOT/baseline_reg/reg.json"     --baseline-quality "$BENCHROOT/baseline-mini/score_v4.json"     --parent-checkpoint "$PARENT"     --checkpoint-reg "$EVALROOT/step-$TAG-reg/reg.json"     --quality "$BENCHROOT/step-$TAG-mini/score_v4.json"     --checkpoint "$CKPT" --index "$i" --state "$STATE"     --max-regression 0.02 --patience 2 | tee "$RUNROOT/gate-step-$TAG.log"

  CURRENT="$CKPT"
  if grep -q '^P59_STOP=1$' "$RUNROOT/gate-step-$TAG.log"; then
    echo "P59_MARK=EARLY_STOP checkpoint=$TAG"
    break
  fi
done

BEST="$(python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); print(d["best_checkpoint"])' "$STATE")"
BEST_INDEX="$(python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); print(d["best_index"])' "$STATE")"
echo "$BEST" > "$RUNROOT/best_checkpoint.txt"
echo "P59_MARK=BEST_CHECKPOINT index=$BEST_INDEX path=$BEST"
if [[ "$BEST_INDEX" == "0" ]]; then
  echo "P59_PIPELINE=NO_IMPROVEMENT_FINAL_REMAINS_SEALED"
  exit 52
fi
echo "P59_MARK=FULL_THERMAL_DEV"
run_gpu "p59-full-dev-$RUN_ID"   python3 /workspace/deploy/stage-p5/benchmark/run_quality_benchmark_v2.py   --model-dir /p5/models/Qwen3.8-27B-buffered-512m   --adapter-dir "${BEST/$DATA//p5}"   --dataset /workspace/deploy/stage-p5/training/p59/p59_thermal_dev_v1.jsonl   --output "/p5/benchmarks/$RUN_ID/full-dev/results.jsonl"   --batch-size 7 --max-new-tokens 140
score_v4 "$ROOT/deploy/stage-p5/training/p59/p59_thermal_dev_v1.jsonl"   "$BENCHROOT/full-dev/results.jsonl"   "$BENCHROOT/full-dev/score_v4.json"   "$RUNROOT/full-dev-score.log"

echo "P59_MARK=BROAD_P58_DEV"
run_gpu "p59-broad-dev-$RUN_ID"   python3 /workspace/deploy/stage-p5/benchmark/run_quality_benchmark_v2.py   --model-dir /p5/models/Qwen3.8-27B-buffered-512m   --adapter-dir "${BEST/$DATA//p5}"   --dataset /workspace/deploy/stage-p5/training/p58/p58_dev_v1.jsonl   --output "/p5/benchmarks/$RUN_ID/p58-dev/results.jsonl"   --batch-size 7 --max-new-tokens 140
score_v4 "$ROOT/deploy/stage-p5/training/p58/p58_dev_v1.jsonl"   "$BENCHROOT/p58-dev/results.jsonl"   "$BENCHROOT/p58-dev/score_v4.json"   "$RUNROOT/p58-dev-score.log"
echo "P59_MARK=FULL_REGRESSION"
run_gpu "p59-full-reg-$RUN_ID"   python3 /workspace/deploy/stage-p5/training/electronics_v4/eval_multi_holdout_v4.py   --model-dir /p5/models/Qwen3.8-27B-buffered-512m   --adapter-dir "${BEST/$DATA//p5}"   --dataset v1=/workspace/deploy/stage-p5/training/electronics/electronics_foundation_holdout_v1.jsonl   --dataset v2=/workspace/deploy/stage-p5/training/electronics_v2/electronics_foundation_v2_holdout.jsonl   --dataset v3=/workspace/deploy/stage-p5/training/electronics_v3/electronics_foundation_v3_holdout.jsonl   --dataset v4=/workspace/deploy/stage-p5/training/electronics_v4/discriminating_measurement_v4_holdout.jsonl   --output-dir "/p5/evals/$RUN_ID/full_regression"

echo "P59_MARK=P57_REGRESSION"
run_gpu "p59-p57reg-$RUN_ID"   python3 /workspace/deploy/stage-p5/benchmark/run_quality_benchmark_v2.py   --model-dir /p5/models/Qwen3.8-27B-buffered-512m   --adapter-dir "${BEST/$DATA//p5}"   --dataset /workspace/deploy/stage-p5/training/p58/p58_p57final_regression.jsonl   --output "/p5/benchmarks/$RUN_ID/p57-regression/results.jsonl"   --batch-size 7 --max-new-tokens 140
score_v4 "$ROOT/deploy/stage-p5/training/p58/p58_p57final_regression.jsonl"   "$BENCHROOT/p57-regression/results.jsonl"   "$BENCHROOT/p57-regression/score_v4.json"   "$RUNROOT/p57-regression-score.log"
echo "P59_MARK=P55_REGRESSION"
run_gpu "p59-p55reg-$RUN_ID"   python3 /workspace/deploy/stage-p5/benchmark/run_quality_benchmark_v2.py   --model-dir /p5/models/Qwen3.8-27B-buffered-512m   --adapter-dir "${BEST/$DATA//p5}"   --dataset /workspace/benchmarks/electronics_v3_quality_v1/cases.v1.jsonl   --output "/p5/benchmarks/$RUN_ID/p55-regression/results.jsonl"   --batch-size 7 --max-new-tokens 140
score_v4 "$ROOT/benchmarks/electronics_v3_quality_v1/cases.v1.jsonl"   "$BENCHROOT/p55-regression/results.jsonl"   "$BENCHROOT/p55-regression/score_v4.json"   "$RUNROOT/p55-regression-score.log"

echo "P59_MARK=PARENT_BASELINES_V4"
score_v4 "$ROOT/deploy/stage-p5/training/p58/p58_p57final_regression.jsonl"   "$P58_BENCH/p57-final-regression/results.jsonl"   "$BENCHROOT/parent-p57-score-v4.json"   "$RUNROOT/parent-p57-score-v4.log"
score_v4 "$ROOT/benchmarks/electronics_v3_quality_v1/cases.v1.jsonl"   "$P58_BENCH/p55-regression/results.jsonl"   "$BENCHROOT/parent-p55-score-v4.json"   "$RUNROOT/parent-p55-score-v4.log"
set +e
python3 "$ROOT/deploy/stage-p5/training/p59/prefinal_gate_p59.py"   --thermal-dev "$BENCHROOT/full-dev/score_v4.json"   --broad-dev "$BENCHROOT/p58-dev/score_v4.json"   --p57-parent "$BENCHROOT/parent-p57-score-v4.json"   --p57-candidate "$BENCHROOT/p57-regression/score_v4.json"   --p55-parent "$BENCHROOT/parent-p55-score-v4.json"   --p55-candidate "$BENCHROOT/p55-regression/score_v4.json"   --parent-v1 "$P58_EVAL/full_regression/v1.json" --candidate-v1 "$EVALROOT/full_regression/v1.json"   --parent-v2 "$P58_EVAL/full_regression/v2.json" --candidate-v2 "$EVALROOT/full_regression/v2.json"   --parent-v3 "$P58_EVAL/full_regression/v3.json" --candidate-v3 "$EVALROOT/full_regression/v3.json"   --parent-v4 "$P58_EVAL/full_regression/v4.json" --candidate-v4 "$EVALROOT/full_regression/v4.json"   --candidate "$BEST" --output "$RUNROOT/prefinal_gate.json" | tee "$RUNROOT/prefinal-gate.log"
PRE_RC=${PIPESTATUS[0]}
set -e
if (( PRE_RC != 0 )); then
  echo "P59_PIPELINE=PREFINAL_FAIL_FINAL_REMAINS_SEALED"
  exit "$PRE_RC"
fi
echo "P59_MARK=P58_FINAL_OPEN sha=$(sha256sum "$ROOT/deploy/stage-p5/training/p58/p58_final_v1.jsonl" | awk '{print $1}')"
run_gpu "p59-final-$RUN_ID"   python3 /workspace/deploy/stage-p5/benchmark/run_quality_benchmark_v2.py   --model-dir /p5/models/Qwen3.8-27B-buffered-512m   --adapter-dir "${BEST/$DATA//p5}"   --dataset /workspace/deploy/stage-p5/training/p58/p58_final_v1.jsonl   --output "/p5/benchmarks/$RUN_ID/final/results.jsonl"   --batch-size 7 --max-new-tokens 140
score_v4 "$ROOT/deploy/stage-p5/training/p58/p58_final_v1.jsonl"   "$BENCHROOT/final/results.jsonl"   "$BENCHROOT/final/score_v4.json"   "$RUNROOT/final-score.log"

set +e
python3 "$ROOT/deploy/stage-p5/training/p59/final_gate_p59.py"   --thermal-dev "$BENCHROOT/full-dev/score_v4.json"   --broad-dev "$BENCHROOT/p58-dev/score_v4.json"   --final-quality "$BENCHROOT/final/score_v4.json"   --p57-parent "$BENCHROOT/parent-p57-score-v4.json"   --p57-candidate "$BENCHROOT/p57-regression/score_v4.json"   --p55-parent "$BENCHROOT/parent-p55-score-v4.json"   --p55-candidate "$BENCHROOT/p55-regression/score_v4.json"   --parent-v1 "$P58_EVAL/full_regression/v1.json" --candidate-v1 "$EVALROOT/full_regression/v1.json"   --parent-v2 "$P58_EVAL/full_regression/v2.json" --candidate-v2 "$EVALROOT/full_regression/v2.json"   --parent-v3 "$P58_EVAL/full_regression/v3.json" --candidate-v3 "$EVALROOT/full_regression/v3.json"   --parent-v4 "$P58_EVAL/full_regression/v4.json" --candidate-v4 "$EVALROOT/full_regression/v4.json"   --candidate "$BEST" --run-id "$RUN_ID" --output "$RUNROOT/final_gate.json"   | tee "$RUNROOT/final-gate.log"
RC=${PIPESTATUS[0]}
set -e

if (( RC==0 )); then
  echo "P59_PIPELINE=QUALIFIED_RUN"
else
  echo "P59_PIPELINE=FINAL_FAIL"
fi
echo "P59_RUN_ID=$RUN_ID"
echo "P59_BEST_CHECKPOINT=$BEST"
exit "$RC"
