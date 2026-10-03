#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../../.." && pwd -P)"
DATA_ROOT="/srv/ai-data/training/p5"
LLAMA_ROOT="${P5_LLAMA_CPP_ROOT:-/home/harrypotter/llama.cpp}"
TRAIN_IMAGE="${P5_TRAIN_IMAGE:-ai-platform-p5-train:rocm7.2.1-v1}"
BASE_MODEL_HF="${P5_BASE_MODEL_HF:-$DATA_ROOT/models/Qwen3.8-27B-buffered-512m}"
BASE_MODEL_OLLAMA="qwen3.8:27b-p4-64k-gpu"
RUNTIME_MODEL="qwen3.8:27b-p4-64k-gpu-p513-wvc-dev"
ADAPTER_ALIAS="${1:?usage: build_qwen38_p513_wvc_runtime.sh /srv/ai-data/training/p5/adapters/wvc-specialization-v1/RUN [--smoke]}"
RUNTIME_ROOT="$DATA_ROOT/runtime-adapters/wvc-specialization-v1"
PATCHER="$ROOT/deploy/stage-p5/runtime/patch_qwen35_lora_outproj.py"

EXPECTED_LLAMA_SHA="34af94cd9ab277632e27caeec2d41de2fd091b31"
EXPECTED_IMAGE_ID="sha256:415b8e68c15d5bf9f7eeb6c4b697327953c600c875456ec5b12fccc1eb5414f8"
SMOKE=0
[[ "${2:-}" == "--smoke" ]] && SMOKE=1
[[ $# -le 2 && ( $# -eq 1 || "${2:-}" == "--smoke" ) ]] || { echo "invalid arguments" >&2; exit 1; }

fail(){ printf 'P513_RUNTIME=FAIL %s\n' "$*" >&2; exit 1; }
for cmd in git docker python3 sha256sum ollama readlink; do
  command -v "$cmd" >/dev/null || fail "missing_command=$cmd"
done

ADAPTER_DIR="$(readlink -f "$ADAPTER_ALIAS" 2>/dev/null || true)"
[[ -d "$ADAPTER_DIR" ]] || fail "missing_adapter_directory"
[[ "$ADAPTER_DIR" == /srv/ai-data/training/p5/adapters/wvc-specialization-v1/* ]] || fail "adapter_outside_p513_root"
[[ -f "$ADAPTER_DIR/adapter_model.safetensors" ]] || fail "missing_adapter_weights"
[[ -f "$ADAPTER_DIR/p513_training_manifest.json" ]] || fail "missing_training_manifest"
[[ -d "$BASE_MODEL_HF" ]] || fail "missing_base_model"
[[ -f "$PATCHER" ]] || fail "missing_converter_patcher"

CONTRACT="$(python3 "$ROOT/deploy/stage-p5/training/wvc_specialization_v1/runtime_contract.py" "$ADAPTER_DIR")" || fail "invalid_p513_manifest"
read -r EXPECTED_ADAPTER_SHA EXPECTED_TENSORS <<<"$CONTRACT"
ACTUAL_ADAPTER_SHA="$(sha256sum "$ADAPTER_DIR/adapter_model.safetensors" | awk '{print $1}')"
[[ "$ACTUAL_ADAPTER_SHA" == "$EXPECTED_ADAPTER_SHA" ]] || fail "adapter_sha_mismatch"
ACTUAL_LLAMA_SHA="$(git -C "$LLAMA_ROOT" rev-parse HEAD)"
[[ "$ACTUAL_LLAMA_SHA" == "$EXPECTED_LLAMA_SHA" ]] || fail "llama_cpp_sha_mismatch"
ACTUAL_IMAGE_ID="$(docker image inspect "$TRAIN_IMAGE" --format '{{.Id}}')"
[[ "$ACTUAL_IMAGE_ID" == "$EXPECTED_IMAGE_ID" ]] || fail "training_image_mismatch"


mkdir -p "$RUNTIME_ROOT"
TMP="$(mktemp -d /tmp/p513-runtime.XXXXXX)"
cleanup(){
  git -C "$LLAMA_ROOT" worktree remove --force "$TMP/llama" >/dev/null 2>&1 || true
  rm -rf "$TMP"
}
trap cleanup EXIT
git -C "$LLAMA_ROOT" worktree add --detach "$TMP/llama" "$EXPECTED_LLAMA_SHA" >/dev/null
python3 "$PATCHER" "$TMP/llama/conversion/qwen.py"

docker run --rm -i --network=none   -v "$TMP/llama:/llama:ro"   "$TRAIN_IMAGE" python3 - <<'PY'
import importlib.util, sys, torch
sys.path.insert(0, "/llama")
spec = importlib.util.spec_from_file_location("lora_conv", "/llama/convert_lora_to_gguf.py")
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)
rank, out_dim, num_k, num_v_per_k, head_dim = 3, 7, 2, 3, 4
in_dim = num_k * num_v_per_k * head_dim
torch.manual_seed(1)
A = torch.randn(rank, in_dim)
B = torch.randn(out_dim, rank)
L = m.LoraTorchTensor(A, B)
idx = torch.arange(in_dim).reshape(1, num_k, num_v_per_k, head_dim).permute(0, 2, 1, 3).contiguous().reshape(-1)
A2, B2 = L[:, idx].get_lora_A_B()
assert torch.equal(B, B2)
assert torch.allclose((B @ A)[:, idx], B2 @ A2, atol=0, rtol=0)
print("P513_LORA_PERMUTATION_EQUIVALENCE=PASS")
PY

IMMUTABLE_GGUF="$RUNTIME_ROOT/p513-qwen38-${EXPECTED_ADAPTER_SHA:0:12}-${EXPECTED_LLAMA_SHA:0:12}.gguf"
[[ ! -e "$IMMUTABLE_GGUF" ]] || fail "immutable_gguf_already_exists"
UIDN="$(id -u)"; GIDN="$(id -g)"
PARTIAL="$IMMUTABLE_GGUF.partial-$$"
docker run --rm --network=none --user "$UIDN:$GIDN"   -v "$TMP/llama:/llama:ro" -v "$DATA_ROOT:/p5" "$TRAIN_IMAGE"   python3 /llama/convert_lora_to_gguf.py   --base /p5/models/Qwen3.8-27B-buffered-512m   --outfile "/p5/runtime-adapters/wvc-specialization-v1/$(basename "$PARTIAL")"   "/p5/adapters/wvc-specialization-v1/$(basename "$ADAPTER_DIR")"
test -s "$PARTIAL" || fail "empty_gguf"
mv "$PARTIAL" "$IMMUTABLE_GGUF"
EXPECTED_GGUF_SHA="$(sha256sum "$IMMUTABLE_GGUF" | awk '{print $1}')"

MODELFILE="$RUNTIME_ROOT/Modelfile.p513"
cat >"$MODELFILE" <<EOF
FROM $BASE_MODEL_OLLAMA
ADAPTER $IMMUTABLE_GGUF
EOF
ollama create "$RUNTIME_MODEL" -f "$MODELFILE" >/dev/null
SHOW="$(ollama show --modelfile "$RUNTIME_MODEL")"
printf '%s\n' "$SHOW" | grep -Fq "ADAPTER /usr/share/ollama/.ollama/models/blobs/sha256-$EXPECTED_GGUF_SHA"   || fail "ollama_adapter_blob_missing"

export P513_TENSORS="$EXPECTED_TENSORS"
export P513_RUNTIME_ROOT="$RUNTIME_ROOT"
export P513_RUNTIME_MODEL="$RUNTIME_MODEL"
export P513_BASE_MODEL="$BASE_MODEL_OLLAMA"
export P513_ADAPTER_DIR="$ADAPTER_DIR"
export P513_ADAPTER_SHA="$EXPECTED_ADAPTER_SHA"
export P513_GGUF="$IMMUTABLE_GGUF"
export P513_GGUF_SHA="$EXPECTED_GGUF_SHA"
export P513_LLAMA_SHA="$EXPECTED_LLAMA_SHA"
export P513_IMAGE_ID="$EXPECTED_IMAGE_ID"
python3 - <<'PY'
import json, os
from datetime import datetime, timezone
root = os.environ["P513_RUNTIME_ROOT"]
m = {
    "schema_version": 1,
    "stage": "P5.13",
    "dev_only": True,
    "status": "RUNTIME_ADAPTER_READY",
    "generated_at": datetime.now(timezone.utc).isoformat(),
    "runtime_model": os.environ["P513_RUNTIME_MODEL"],
    "base_ollama_model": os.environ["P513_BASE_MODEL"],
    "source_adapter": os.environ["P513_ADAPTER_DIR"],
    "adapter_tensor_count": int(os.environ["P513_TENSORS"]),
    "source_adapter_sha256": os.environ["P513_ADAPTER_SHA"],
    "runtime_gguf": os.environ["P513_GGUF"],
    "runtime_gguf_sha256": os.environ["P513_GGUF_SHA"],
    "llama_cpp_sha": os.environ["P513_LLAMA_SHA"],
    "training_image_id": os.environ["P513_IMAGE_ID"],
    "training_acceptance": "TRAINING_INTEGRITY_PASS_QUALITY_PENDING",
    "quality_acceptance": "PENDING_WVC_BASELINE_REVIEW",
}
open(root + "/runtime_manifest.json", "w", encoding="utf-8").write(json.dumps(m, indent=2, sort_keys=True) + "\n")
print("P513_RUNTIME_MANIFEST=PASS")
PY

if (( SMOKE )); then
  python3 "$ROOT/deploy/stage-p5/training/wvc_specialization_v1/evaluate_wvc_specialization_v1.py"     --models qwen3.8:27b-p4-64k-gpu-p511 "$RUNTIME_MODEL"     --output "$RUNTIME_ROOT/smoke-results.json"
fi

printf 'P513_RUNTIME=PASS\n'
printf 'P513_RUNTIME_MODEL=%s\n' "$RUNTIME_MODEL"
printf 'P513_SOURCE_ADAPTER_SHA256=%s\n' "$EXPECTED_ADAPTER_SHA"
printf 'P513_RUNTIME_GGUF_SHA256=%s\n' "$EXPECTED_GGUF_SHA"
