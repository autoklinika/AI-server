#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../../.." && pwd -P)"
DATA_ROOT="${P5_DATA_ROOT:-/srv/ai-data/training/p5}"
LLAMA_ROOT="${P5_LLAMA_CPP_ROOT:-/home/harrypotter/llama.cpp}"
TRAIN_IMAGE="${P5_TRAIN_IMAGE:-ai-platform-p5-train:rocm7.2.1-v1}"
BASE_MODEL_HF="${P5_BASE_MODEL_HF:-$DATA_ROOT/models/Qwen3.8-27B-buffered-512m}"
BASE_MODEL_OLLAMA="qwen3.8:27b-p4-64k-gpu"
RUNTIME_MODEL="qwen3.8:27b-p4-64k-gpu-p511"
ADAPTER_ALIAS="$DATA_ROOT/adapters/automotive-specialization-v1/current"
RUNTIME_ROOT="$DATA_ROOT/runtime-adapters/automotive-specialization-v1"
PATCHER="$ROOT/deploy/stage-p5/runtime/patch_qwen35_lora_outproj.py"

EXPECTED_LLAMA_SHA="34af94cd9ab277632e27caeec2d41de2fd091b31"
EXPECTED_IMAGE_ID="sha256:415b8e68c15d5bf9f7eeb6c4b697327953c600c875456ec5b12fccc1eb5414f8"
EXPECTED_ADAPTER_SHA="46f38a1d4a4c26ce7800a4e05be8cbcb23da8b8f460e6f7faa8a73d577defdcb"
EXPECTED_GGUF_SHA="bb4966fa3d8a5a71a7e21b159235cc5e00f0282ff6c50ce6c1c41eca2dbba8a7"
EXPECTED_TENSORS=992
SMOKE=0
[[ "${1:-}" == "--smoke" ]] && SMOKE=1

fail(){ printf 'P511_RUNTIME=FAIL %s\n' "$*" >&2; exit 1; }
for cmd in git docker python3 sha256sum ollama readlink; do
  command -v "$cmd" >/dev/null || fail "missing_command=$cmd"
done

ADAPTER_DIR="$(readlink -f "$ADAPTER_ALIAS" 2>/dev/null || true)"
[[ -d "$ADAPTER_DIR" ]] || fail "missing_adapter_alias"
[[ -f "$ADAPTER_DIR/adapter_model.safetensors" ]] || fail "missing_adapter_weights"
[[ -f "$ADAPTER_DIR/p511_training_manifest.json" ]] || fail "missing_training_manifest"
[[ -d "$BASE_MODEL_HF" ]] || fail "missing_base_model"
[[ -f "$PATCHER" ]] || fail "missing_converter_patcher"

ACTUAL_ADAPTER_SHA="$(sha256sum "$ADAPTER_DIR/adapter_model.safetensors" | awk '{print $1}')"
[[ "$ACTUAL_ADAPTER_SHA" == "$EXPECTED_ADAPTER_SHA" ]] || fail "adapter_sha_mismatch"
ACTUAL_LLAMA_SHA="$(git -C "$LLAMA_ROOT" rev-parse HEAD)"
[[ "$ACTUAL_LLAMA_SHA" == "$EXPECTED_LLAMA_SHA" ]] || fail "llama_cpp_sha_mismatch"
ACTUAL_IMAGE_ID="$(docker image inspect "$TRAIN_IMAGE" --format '{{.Id}}')"
[[ "$ACTUAL_IMAGE_ID" == "$EXPECTED_IMAGE_ID" ]] || fail "training_image_mismatch"

python3 - "$ADAPTER_DIR/p511_training_manifest.json" "$EXPECTED_ADAPTER_SHA" "$EXPECTED_TENSORS" <<'PY'
import json, sys
path, expected_sha, expected_tensors = sys.argv[1], sys.argv[2], int(sys.argv[3])
m = json.load(open(path, encoding="utf-8"))
assert m["status"] == "TRAINING_INTEGRITY_PASS_QUALITY_PENDING"
assert m["adapter_kind"] == "standalone_lora_not_merged"
assert m["base_model"] == "Qwen/Qwen3.8-27B"
assert m["adapter_sha256"] == expected_sha
assert m["adapter_tensor_count"] == expected_tensors
assert m["config"]["lora_r"] == 8
assert m["quality_acceptance"] == "PENDING_FUTURE_INDEPENDENT_EVALUATION"
print("P511_TRAINING_MANIFEST=PASS")
PY

mkdir -p "$RUNTIME_ROOT"
TMP="$(mktemp -d /tmp/p511-runtime.XXXXXX)"
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
print("P511_LORA_PERMUTATION_EQUIVALENCE=PASS")
PY

IMMUTABLE_GGUF="$RUNTIME_ROOT/p511-qwen38-${EXPECTED_ADAPTER_SHA:0:12}-${EXPECTED_LLAMA_SHA:0:12}.gguf"
if [[ -f "$IMMUTABLE_GGUF" ]]; then
  EXISTING_SHA="$(sha256sum "$IMMUTABLE_GGUF" | awk '{print $1}')"
  [[ "$EXISTING_SHA" == "$EXPECTED_GGUF_SHA" ]] || fail "existing_gguf_sha_mismatch"
else
  UIDN="$(id -u)"; GIDN="$(id -g)"
  docker run --rm --network=none --user "$UIDN:$GIDN"     -v "$TMP/llama:/llama:ro" -v "$DATA_ROOT:/p5"     "$TRAIN_IMAGE"     python3 /llama/convert_lora_to_gguf.py       --base /p5/models/Qwen3.8-27B-buffered-512m       --outfile "/p5/runtime-adapters/automotive-specialization-v1/$(basename "$IMMUTABLE_GGUF")"       "/p5/adapters/automotive-specialization-v1/$(basename "$ADAPTER_DIR")"
fi
ACTUAL_GGUF_SHA="$(sha256sum "$IMMUTABLE_GGUF" | awk '{print $1}')"
[[ "$ACTUAL_GGUF_SHA" == "$EXPECTED_GGUF_SHA" ]] || fail "gguf_sha_mismatch"
ln -sfn "$IMMUTABLE_GGUF" "$RUNTIME_ROOT/current.gguf"

MODELFILE="$RUNTIME_ROOT/Modelfile.p511"
cat >"$MODELFILE" <<EOF
FROM $BASE_MODEL_OLLAMA
ADAPTER $IMMUTABLE_GGUF
EOF
ollama create "$RUNTIME_MODEL" -f "$MODELFILE" >/dev/null
SHOW="$(ollama show --modelfile "$RUNTIME_MODEL")"
printf '%s\n' "$SHOW" | grep -Fq "ADAPTER /usr/share/ollama/.ollama/models/blobs/sha256-$EXPECTED_GGUF_SHA"   || fail "ollama_adapter_blob_missing"

export P511_RUNTIME_ROOT="$RUNTIME_ROOT"
export P511_RUNTIME_MODEL="$RUNTIME_MODEL"
export P511_BASE_MODEL="$BASE_MODEL_OLLAMA"
export P511_ADAPTER_DIR="$ADAPTER_DIR"
export P511_ADAPTER_SHA="$EXPECTED_ADAPTER_SHA"
export P511_GGUF="$IMMUTABLE_GGUF"
export P511_GGUF_SHA="$EXPECTED_GGUF_SHA"
export P511_LLAMA_SHA="$EXPECTED_LLAMA_SHA"
export P511_IMAGE_ID="$EXPECTED_IMAGE_ID"
python3 - <<'PY'
import json, os
from datetime import datetime, timezone
root = os.environ["P511_RUNTIME_ROOT"]
m = {
    "schema_version": 1,
    "status": "RUNTIME_ADAPTER_READY",
    "generated_at": datetime.now(timezone.utc).isoformat(),
    "runtime_model": os.environ["P511_RUNTIME_MODEL"],
    "base_ollama_model": os.environ["P511_BASE_MODEL"],
    "source_adapter": os.environ["P511_ADAPTER_DIR"],
    "source_adapter_sha256": os.environ["P511_ADAPTER_SHA"],
    "runtime_gguf": os.environ["P511_GGUF"],
    "runtime_gguf_sha256": os.environ["P511_GGUF_SHA"],
    "llama_cpp_sha": os.environ["P511_LLAMA_SHA"],
    "training_image_id": os.environ["P511_IMAGE_ID"],
    "training_acceptance": "TRAINING_INTEGRITY_PASS_QUALITY_PENDING",
    "quality_acceptance": "PENDING_FUTURE_INDEPENDENT_EVALUATION",
}
open(root + "/runtime_manifest.json", "w", encoding="utf-8").write(json.dumps(m, indent=2, sort_keys=True) + "\n")
print("P511_RUNTIME_MANIFEST=PASS")
PY

if (( SMOKE )); then
  export P511_SMOKE_MODEL="$RUNTIME_MODEL"
  python3 - <<'PY'
import json, os, urllib.request
payload = {
    "model": os.environ["P511_SMOKE_MODEL"],
    "prompt": (
        "Odpowiedz po polsku. ECU po nagrzaniu traci sterowanie elektrozaworem, "
        "ale zasilanie ECU pozostaje stabilne. Podaj dwa możliwe kierunki diagnostyczne "
        "i jeden pomiar rozdzielający usterkę sterownika od obciążenia."
    ),
    "stream": False,
    "think": False,
    "keep_alive": "0s",
    "options": {"temperature": 0, "num_ctx": 4096, "num_predict": 160},
}
req = urllib.request.Request(
    "http://127.0.0.1:11434/api/generate",
    data=json.dumps(payload).encode(),
    headers={"Content-Type": "application/json"},
)
with urllib.request.urlopen(req, timeout=300) as response:
    result = json.load(response)
text = (result.get("response") or "").strip()
assert result.get("done") is True and len(text) >= 80
print("P511_OLLAMA_INFERENCE=PASS")
print(text)
PY
fi

printf 'P511_RUNTIME=PASS\n'
printf 'P511_RUNTIME_MODEL=%s\n' "$RUNTIME_MODEL"
printf 'P511_SOURCE_ADAPTER_SHA256=%s\n' "$EXPECTED_ADAPTER_SHA"
printf 'P511_RUNTIME_GGUF_SHA256=%s\n' "$EXPECTED_GGUF_SHA"
