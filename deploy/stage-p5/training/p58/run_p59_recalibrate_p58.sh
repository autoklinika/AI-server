#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
DATA="${P5_DATA_ROOT:-/srv/ai-data/training/p5}"
MODEL="${P5_MODEL_DIR:-$DATA/models/Qwen3.8-27B-buffered-512m}"
IMAGE="${P5_TRAIN_IMAGE:-ai-platform-p5-train:rocm7.2.1-v1}"
P58_RUN="${P58_RUN_ID:-p58-seed1-20261001}"
RUN_ID="${P59_RUN_ID:-p59-recalibrate-p58-20261001}"
BEST="$DATA/checkpoints/p58-$P58_RUN/step-008"
OUT="$DATA/p59/$RUN_ID"
B="$DATA/benchmarks/$P58_RUN"
E="$DATA/evals/$P58_RUN"
mkdir -p "$OUT" "$B/recalibrated-v4"

test -f "$BEST/adapter_config.json"
test -f "$B/full-dev/results.jsonl"
test -f "$B/p57-final-regression/results.jsonl"
test -f "$B/p55-regression/results.jsonl"
for v in v1 v2 v3 v4; do test -f "$E/full_regression/$v.json"; done

# P58 FINAL must still be sealed before recalibration.
if [[ -s "$B/final/results.jsonl" ]]; then
  echo "P59_RECALIBRATION=BLOCKED_FINAL_ALREADY_OPEN" >&2
  exit 61
fi

score_v4() {
  local dataset="$1" results="$2" output="$3"
  python3 "$ROOT/deploy/stage-p5/benchmark/score_quality_benchmark_v4.py"     --dataset "$dataset" --results "$results" --output "$output"
}

echo "P59_MARK=RESCORE_DEV"
score_v4 "$ROOT/deploy/stage-p5/training/p58/p58_dev_v1.jsonl"   "$B/full-dev/results.jsonl" "$B/recalibrated-v4/full-dev-score.json" | tee "$OUT/full-dev-v4.log"

echo "P59_MARK=RESCORE_P57_PARENT"
score_v4 "$ROOT/deploy/stage-p5/training/p57/p57_final_v1.jsonl"   "$DATA/benchmarks/p57-seed1b-20261001/final/results.jsonl"   "$B/recalibrated-v4/p57-parent-score.json" | tee "$OUT/p57-parent-v4.log"

echo "P59_MARK=RESCORE_P57_CANDIDATE"
score_v4 "$ROOT/deploy/stage-p5/training/p58/p58_p57final_regression.jsonl"   "$B/p57-final-regression/results.jsonl"   "$B/recalibrated-v4/p57-candidate-score.json" | tee "$OUT/p57-candidate-v4.log"

echo "P59_MARK=RESCORE_P55_PARENT"
score_v4 "$ROOT/benchmarks/electronics_v3_quality_v1/cases.v1.jsonl"   "$DATA/benchmarks/p57-seed1b-20261001/legacy-p55/results.jsonl"   "$B/recalibrated-v4/p55-parent-score.json" | tee "$OUT/p55-parent-v4.log"

echo "P59_MARK=RESCORE_P55_CANDIDATE"
score_v4 "$ROOT/benchmarks/electronics_v3_quality_v1/cases.v1.jsonl"   "$B/p55-regression/results.jsonl"   "$B/recalibrated-v4/p55-candidate-score.json" | tee "$OUT/p55-candidate-v4.log"

ollama stop bge-m3 >/dev/null 2>&1 || true
sleep 2

set +e
python3 "$ROOT/deploy/stage-p5/training/p58/prefinal_gate_p58.py"   --dev-quality "$B/recalibrated-v4/full-dev-score.json"   --p57-parent "$B/recalibrated-v4/p57-parent-score.json"   --p57-candidate "$B/recalibrated-v4/p57-candidate-score.json"   --p55-parent "$B/recalibrated-v4/p55-parent-score.json"   --p55-candidate "$B/recalibrated-v4/p55-candidate-score.json"   --parent-v1 "$DATA/evals/p57-seed1b-20261001/full_regression/v1.json" --candidate-v1 "$E/full_regression/v1.json"   --parent-v2 "$DATA/evals/p57-seed1b-20261001/full_regression/v2.json" --candidate-v2 "$E/full_regression/v2.json"   --parent-v3 "$DATA/evals/p57-seed1b-20261001/full_regression/v3.json" --candidate-v3 "$E/full_regression/v3.json"   --parent-v4 "$DATA/evals/p57-seed1b-20261001/full_regression/v4.json" --candidate-v4 "$E/full_regression/v4.json"   --candidate "$BEST" --output "$OUT/prefinal_gate_v4.json" | tee "$OUT/prefinal-v4.log"
PRE_RC=${PIPESTATUS[0]}
set -e

if (( PRE_RC != 0 )); then
  echo "P59_RECALIBRATION=PREFINAL_FAIL_FINAL_REMAINS_SEALED"
  exit "$PRE_RC"
fi

echo "P59_MARK=P58_FINAL_OPEN sha=$(sha256sum "$ROOT/deploy/stage-p5/training/p58/p58_final_v1.jsonl" | awk '{print $1}')"

if ollama ps 2>/dev/null | tail -n +2 | grep -q .; then
  echo "P59=BLOCKED ollama_resident" >&2
  exit 43
fi
MES_BASE="$(journalctl -b -k --no-pager | grep -c "MES ring buffer is full" || true)"
UIDN="$(id -u)"; GIDN="$(id -g)"; RGID="$(getent group render|cut -d: -f3)"; VGID="$(getent group video|cut -d: -f3)"
GIT_SHA="$(git -C "$ROOT" rev-parse HEAD)"

docker run --rm --name "p59-p58-final-$RUN_ID" --memory=48g --memory-swap=48g   --user "$UIDN:$GIDN" --group-add "$RGID" --group-add "$VGID"   --device=/dev/kfd --device=/dev/dri --ipc=host --shm-size=8g   -e HOME=/p5/tmp/home -e HF_HOME=/p5/hf-cache -e P5_GIT_SHA="$GIT_SHA"   -v "$DATA:/p5" -v "$ROOT:/workspace:ro" "$IMAGE"   python3 /workspace/deploy/stage-p5/benchmark/run_quality_benchmark_v2.py     --model-dir /p5/models/Qwen3.8-27B-buffered-512m     --adapter-dir "${BEST/$DATA//p5}"     --dataset /workspace/deploy/stage-p5/training/p58/p58_final_v1.jsonl     --output "/p5/benchmarks/$P58_RUN/final/results.jsonl"     --batch-size 7 --max-new-tokens 140 &
DP=$!
while kill -0 "$DP" 2>/dev/null; do
  sleep 2
  MES_NOW="$(journalctl -b -k --no-pager | grep -c "MES ring buffer is full" || true)"
  if (( MES_NOW > MES_BASE )); then
    docker kill "p59-p58-final-$RUN_ID" >/dev/null 2>&1 || true
    wait "$DP" || true
    echo "P59=FAIL mes_increment baseline=$MES_BASE current=$MES_NOW" >&2
    exit 89
  fi
done
wait "$DP"

score_v4 "$ROOT/deploy/stage-p5/training/p58/p58_final_v1.jsonl"   "$B/final/results.jsonl" "$B/recalibrated-v4/final-score.json" | tee "$OUT/final-v4.log"
ollama stop bge-m3 >/dev/null 2>&1 || true

set +e
python3 "$ROOT/deploy/stage-p5/training/p58/final_gate_p58.py"   --dev-quality "$B/recalibrated-v4/full-dev-score.json"   --final-quality "$B/recalibrated-v4/final-score.json"   --p57-parent "$B/recalibrated-v4/p57-parent-score.json"   --p57-candidate "$B/recalibrated-v4/p57-candidate-score.json"   --p55-parent "$B/recalibrated-v4/p55-parent-score.json"   --p55-candidate "$B/recalibrated-v4/p55-candidate-score.json"   --parent-v1 "$DATA/evals/p57-seed1b-20261001/full_regression/v1.json" --candidate-v1 "$E/full_regression/v1.json"   --parent-v2 "$DATA/evals/p57-seed1b-20261001/full_regression/v2.json" --candidate-v2 "$E/full_regression/v2.json"   --parent-v3 "$DATA/evals/p57-seed1b-20261001/full_regression/v3.json" --candidate-v3 "$E/full_regression/v3.json"   --parent-v4 "$DATA/evals/p57-seed1b-20261001/full_regression/v4.json" --candidate-v4 "$E/full_regression/v4.json"   --candidate "$BEST" --run-id "$RUN_ID" --output "$OUT/final_gate_v4.json" | tee "$OUT/final-gate-v4.log"
RC=${PIPESTATUS[0]}
set -e

if (( RC==0 )); then
  echo "P59_RECALIBRATION=QUALIFIED_RUN"
else
  echo "P59_RECALIBRATION=FINAL_FAIL"
fi
exit "$RC"
