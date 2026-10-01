#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
DATA="${P5_DATA_ROOT:-/srv/ai-data/training/p5}"
MODEL="${P5_MODEL_DIR:-$DATA/models/Qwen3.8-27B-buffered-512m}"
PARENT="${P58_PARENT_ADAPTER:-$DATA/checkpoints/p57-p57-seed1b-20261001/step-008}"
IMAGE="${P5_TRAIN_IMAGE:-ai-platform-p5-train:rocm7.2.1-v1}"
RUN_ID="${P58_RUN_ID:-p58-seed1-$(date -u +%Y%m%dT%H%M%SZ)}"
SEED="${P58_SEED:-20261008}"
INTERVAL="${P58_CHECKPOINT_INTERVAL:-8}"
MAX_CKPT="${P58_MAX_CHECKPOINTS:-10}"
LR="${P58_LR:-0.0000005}"
MAXLEN="${P58_MAX_LENGTH:-512}"
RUNROOT="$DATA/p58/$RUN_ID"
CKPTROOT="$DATA/checkpoints/p58-$RUN_ID"
EVALROOT="$DATA/evals/$RUN_ID"
BENCHROOT="$DATA/benchmarks/$RUN_ID"
STATE="$RUNROOT/state.json"
mkdir -p "$RUNROOT" "$CKPTROOT" "$EVALROOT" "$BENCHROOT"
GIT_SHA="$(git -C "$ROOT" rev-parse HEAD)"

python3 "$ROOT/deploy/stage-p5/training/p58/prepare_p58_data.py" >"$RUNROOT/data.log"
python3 "$ROOT/deploy/stage-p5/training/p58/validate_p58.py" | tee "$RUNROOT/readiness.log"
grep -q '^P58_READINESS=PASS$' "$RUNROOT/readiness.log"
test -f "$PARENT/adapter_config.json"; test -f "$MODEL/model.safetensors.index.json"

ollama stop bge-m3 >/dev/null 2>&1 || true
sleep 2
if ollama ps 2>/dev/null | tail -n +2 | grep -q .; then echo "P58=BLOCKED ollama_resident" >&2; exit 43; fi
VRAM="$(cat /sys/class/drm/card0/device/mem_info_vram_used)"
if (( VRAM > 2147483648 )); then echo "P58=BLOCKED vram_used=$VRAM" >&2; exit 42; fi
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
      echo "P58=FAIL mes_increment baseline=$MES_BASE current=$mes" >&2; exit 89
    fi
  done
  wait "$dp"
}
echo "P58_MARK=BASELINE_REGRESSION"
run_gpu "p58-base-reg-$RUN_ID" python3 /workspace/deploy/stage-p5/training/electronics_v4/eval_multi_holdout_v4.py   --model-dir /p5/models/Qwen3.8-27B-buffered-512m   --adapter-dir "${PARENT/$DATA//p5}"   --dataset reg=/workspace/deploy/stage-p5/training/p57/p57_regression_slice_v1.jsonl   --output-dir "/p5/evals/$RUN_ID/baseline_reg"

CURRENT="$PARENT"
for ((i=1;i<=MAX_CKPT;i++)); do
  TOTAL=$((i*INTERVAL)); START=$(((i-1)*INTERVAL)); TAG="$(printf '%03d' "$TOTAL")"
  CKPT="$CKPTROOT/step-$TAG"
  echo "P58_MARK=TRAIN_CHECKPOINT index=$i total_steps=$TOTAL parent=$CURRENT"
  run_gpu "p58-train-$i-$RUN_ID" python3 /workspace/deploy/stage-p5/training/microtrain_lora_bf16.py     --model-dir /p5/models/Qwen3.8-27B-buffered-512m     --dataset /workspace/deploy/stage-p5/training/p58/p58_curriculum_train.jsonl     --output-dir "${CKPT/$DATA//p5}" --steps "$INTERVAL" --max-length "$MAXLEN"     --seed "$((SEED+i))" --lora-r 8 --lr "$LR"     --adapter-dir "${CURRENT/$DATA//p5}" --start-index "$START"     --purpose "P5.8 competency curriculum; checkpoint=$TOTAL; P57-FINAL regression-only; P58-FINAL sealed; never merged into Qwen base"     2>&1 | tee "$RUNROOT/train-step-$TAG.log"

  run_gpu "p58-reg-$i-$RUN_ID" python3 /workspace/deploy/stage-p5/training/electronics_v4/eval_multi_holdout_v4.py     --model-dir /p5/models/Qwen3.8-27B-buffered-512m --adapter-dir "${CKPT/$DATA//p5}"     --dataset reg=/workspace/deploy/stage-p5/training/p57/p57_regression_slice_v1.jsonl     --output-dir "/p5/evals/$RUN_ID/step-$TAG-reg"

  run_gpu "p58-dev-$i-$RUN_ID" python3 /workspace/deploy/stage-p5/benchmark/run_quality_benchmark_v2.py     --model-dir /p5/models/Qwen3.8-27B-buffered-512m --adapter-dir "${CKPT/$DATA//p5}"     --dataset /workspace/deploy/stage-p5/training/p58/p58_mini_dev_v1.jsonl     --output "/p5/benchmarks/$RUN_ID/step-$TAG-mini/results.jsonl" --batch-size 7 --max-new-tokens 140

  python3 "$ROOT/deploy/stage-p5/benchmark/score_quality_benchmark_v3.py"     --dataset "$ROOT/deploy/stage-p5/training/p58/p58_mini_dev_v1.jsonl"     --results "$BENCHROOT/step-$TAG-mini/results.jsonl"     --output "$BENCHROOT/step-$TAG-mini/score_v3.json" | tee "$RUNROOT/score-step-$TAG.log"
  ollama stop bge-m3 >/dev/null 2>&1 || true

  python3 "$ROOT/deploy/stage-p5/training/p57/checkpoint_gate.py"     --baseline-reg "$EVALROOT/baseline_reg/reg.json"     --checkpoint-reg "$EVALROOT/step-$TAG-reg/reg.json"     --quality "$BENCHROOT/step-$TAG-mini/score_v3.json"     --checkpoint "$CKPT" --index "$i" --state "$STATE" --max-regression 0.02 --patience 2     | tee "$RUNROOT/gate-step-$TAG.log"

  CURRENT="$CKPT"
  if grep -q '^P57_STOP=1$' "$RUNROOT/gate-step-$TAG.log"; then
    echo "P58_MARK=EARLY_STOP checkpoint=$TAG"
    break
  fi
done

BEST="$(python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); print(d.get("best_checkpoint") or "")' "$STATE")"
if [[ -z "$BEST" || ! -f "$BEST/adapter_config.json" ]]; then echo "P58=FAIL no_eligible_checkpoint" >&2; exit 51; fi
echo "$BEST" > "$RUNROOT/best_checkpoint.txt"
echo "P58_MARK=BEST_CHECKPOINT path=$BEST"
run_gpu "p58-full-dev-$RUN_ID" python3 /workspace/deploy/stage-p5/benchmark/run_quality_benchmark_v2.py   --model-dir /p5/models/Qwen3.8-27B-buffered-512m --adapter-dir "${BEST/$DATA//p5}"   --dataset /workspace/deploy/stage-p5/training/p58/p58_dev_v1.jsonl   --output "/p5/benchmarks/$RUN_ID/full-dev/results.jsonl" --batch-size 7 --max-new-tokens 140
python3 "$ROOT/deploy/stage-p5/benchmark/score_quality_benchmark_v3.py"   --dataset "$ROOT/deploy/stage-p5/training/p58/p58_dev_v1.jsonl"   --results "$BENCHROOT/full-dev/results.jsonl" --output "$BENCHROOT/full-dev/score_v3.json"   | tee "$RUNROOT/full-dev-score.log"
ollama stop bge-m3 >/dev/null 2>&1 || true

run_gpu "p58-full-reg-$RUN_ID" python3 /workspace/deploy/stage-p5/training/electronics_v4/eval_multi_holdout_v4.py   --model-dir /p5/models/Qwen3.8-27B-buffered-512m --adapter-dir "${BEST/$DATA//p5}"   --dataset v1=/workspace/deploy/stage-p5/training/electronics/electronics_foundation_holdout_v1.jsonl   --dataset v2=/workspace/deploy/stage-p5/training/electronics_v2/electronics_foundation_v2_holdout.jsonl   --dataset v3=/workspace/deploy/stage-p5/training/electronics_v3/electronics_foundation_v3_holdout.jsonl   --dataset v4=/workspace/deploy/stage-p5/training/electronics_v4/discriminating_measurement_v4_holdout.jsonl   --output-dir "/p5/evals/$RUN_ID/full_regression"

run_gpu "p58-p57reg-$RUN_ID" python3 /workspace/deploy/stage-p5/benchmark/run_quality_benchmark_v2.py   --model-dir /p5/models/Qwen3.8-27B-buffered-512m --adapter-dir "${BEST/$DATA//p5}"   --dataset /workspace/deploy/stage-p5/training/p58/p58_p57final_regression.jsonl   --output "/p5/benchmarks/$RUN_ID/p57-final-regression/results.jsonl" --batch-size 7 --max-new-tokens 140
python3 "$ROOT/deploy/stage-p5/benchmark/score_quality_benchmark_v3.py"   --dataset "$ROOT/deploy/stage-p5/training/p58/p58_p57final_regression.jsonl"   --results "$BENCHROOT/p57-final-regression/results.jsonl"   --output "$BENCHROOT/p57-final-regression/score_v3.json" | tee "$RUNROOT/p57-final-regression-score.log"
ollama stop bge-m3 >/dev/null 2>&1 || true

run_gpu "p58-p55reg-$RUN_ID" python3 /workspace/deploy/stage-p5/benchmark/run_quality_benchmark_v2.py   --model-dir /p5/models/Qwen3.8-27B-buffered-512m --adapter-dir "${BEST/$DATA//p5}"   --dataset /workspace/benchmarks/electronics_v3_quality_v1/cases.v1.jsonl   --output "/p5/benchmarks/$RUN_ID/p55-regression/results.jsonl" --batch-size 7 --max-new-tokens 140
python3 "$ROOT/deploy/stage-p5/benchmark/score_quality_benchmark_v3.py"   --dataset "$ROOT/benchmarks/electronics_v3_quality_v1/cases.v1.jsonl"   --results "$BENCHROOT/p55-regression/results.jsonl" --output "$BENCHROOT/p55-regression/score_v3.json"   | tee "$RUNROOT/p55-regression-score.log"
ollama stop bge-m3 >/dev/null 2>&1 || true
set +e
python3 "$ROOT/deploy/stage-p5/training/p58/prefinal_gate_p58.py"   --dev-quality "$BENCHROOT/full-dev/score_v3.json"   --p57-parent "$DATA/benchmarks/p57-seed1b-20261001/final/score_v3.json"   --p57-candidate "$BENCHROOT/p57-final-regression/score_v3.json"   --p55-parent "$DATA/benchmarks/p57-seed1b-20261001/legacy-p55/score_v3.json"   --p55-candidate "$BENCHROOT/p55-regression/score_v3.json"   --parent-v1 "$DATA/evals/p57-seed1b-20261001/full_regression/v1.json" --candidate-v1 "$EVALROOT/full_regression/v1.json"   --parent-v2 "$DATA/evals/p57-seed1b-20261001/full_regression/v2.json" --candidate-v2 "$EVALROOT/full_regression/v2.json"   --parent-v3 "$DATA/evals/p57-seed1b-20261001/full_regression/v3.json" --candidate-v3 "$EVALROOT/full_regression/v3.json"   --parent-v4 "$DATA/evals/p57-seed1b-20261001/full_regression/v4.json" --candidate-v4 "$EVALROOT/full_regression/v4.json"   --candidate "$BEST" --output "$RUNROOT/prefinal_gate.json" | tee "$RUNROOT/prefinal-gate.log"
PRE_RC=${PIPESTATUS[0]}
set -e
if (( PRE_RC != 0 )); then
  echo "P58_PIPELINE=PREFINAL_FAIL_FINAL_REMAINS_SEALED"
  echo "P58_RUN_ID=$RUN_ID"
  echo "P58_BEST_CHECKPOINT=$BEST"
  exit "$PRE_RC"
fi

echo "P58_MARK=FINAL_OPEN sha=$(sha256sum "$ROOT/deploy/stage-p5/training/p58/p58_final_v1.jsonl" | awk '{print $1}')"
run_gpu "p58-final-$RUN_ID" python3 /workspace/deploy/stage-p5/benchmark/run_quality_benchmark_v2.py   --model-dir /p5/models/Qwen3.8-27B-buffered-512m --adapter-dir "${BEST/$DATA//p5}"   --dataset /workspace/deploy/stage-p5/training/p58/p58_final_v1.jsonl   --output "/p5/benchmarks/$RUN_ID/final/results.jsonl" --batch-size 7 --max-new-tokens 140
python3 "$ROOT/deploy/stage-p5/benchmark/score_quality_benchmark_v3.py"   --dataset "$ROOT/deploy/stage-p5/training/p58/p58_final_v1.jsonl"   --results "$BENCHROOT/final/results.jsonl" --output "$BENCHROOT/final/score_v3.json"   | tee "$RUNROOT/final-score.log"
ollama stop bge-m3 >/dev/null 2>&1 || true

set +e
python3 "$ROOT/deploy/stage-p5/training/p58/final_gate_p58.py"   --dev-quality "$BENCHROOT/full-dev/score_v3.json" --final-quality "$BENCHROOT/final/score_v3.json"   --p57-parent "$DATA/benchmarks/p57-seed1b-20261001/final/score_v3.json"   --p57-candidate "$BENCHROOT/p57-final-regression/score_v3.json"   --p55-parent "$DATA/benchmarks/p57-seed1b-20261001/legacy-p55/score_v3.json"   --p55-candidate "$BENCHROOT/p55-regression/score_v3.json"   --parent-v1 "$DATA/evals/p57-seed1b-20261001/full_regression/v1.json" --candidate-v1 "$EVALROOT/full_regression/v1.json"   --parent-v2 "$DATA/evals/p57-seed1b-20261001/full_regression/v2.json" --candidate-v2 "$EVALROOT/full_regression/v2.json"   --parent-v3 "$DATA/evals/p57-seed1b-20261001/full_regression/v3.json" --candidate-v3 "$EVALROOT/full_regression/v3.json"   --parent-v4 "$DATA/evals/p57-seed1b-20261001/full_regression/v4.json" --candidate-v4 "$EVALROOT/full_regression/v4.json"   --candidate "$BEST" --run-id "$RUN_ID" --output "$RUNROOT/final_gate.json" | tee "$RUNROOT/final-gate.log"
RC=${PIPESTATUS[0]}
set -e
if (( RC==0 )); then echo "P58_PIPELINE=QUALIFIED_RUN"; else echo "P58_PIPELINE=FINAL_FAIL"; fi
echo "P58_RUN_ID=$RUN_ID"
echo "P58_BEST_CHECKPOINT=$BEST"
exit "$RC"
