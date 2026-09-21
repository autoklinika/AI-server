#!/usr/bin/env bash
set -euo pipefail

DEST="${1:?usage: $0 DEST RELEASE_ID}"
RELEASE_ID="${2:?usage: $0 DEST RELEASE_ID}"
ROOT="$(git rev-parse --show-toplevel)"
SOURCE_SHA="$(git -C "$ROOT" rev-parse HEAD)"
BASE_GATEWAY_SHA="0e53bbc6f2fad703c46e00526d1bbecedb378438"

say(){ printf '%s\n' "$*"; }
fail(){ say "FAIL: $*" >&2; exit 1; }

[[ -z "$(git -C "$ROOT" status --porcelain)" ]] || fail "working tree must be clean"
[[ ! -e "$DEST" ]] || fail "destination already exists: $DEST"
git -C "$ROOT" cat-file -e "$SOURCE_SHA^{commit}" || fail "invalid source commit"

# Stage C must not change scheduler code or dependency declarations.
git -C "$ROOT" diff --quiet "$BASE_GATEWAY_SHA" "$SOURCE_SHA" -- src/ai_bridge/gateway   || fail "Stage C source changes AI Gateway scheduler code"
git -C "$ROOT" diff --quiet "$BASE_GATEWAY_SHA" "$SOURCE_SHA" -- pyproject.toml   || fail "pyproject changed; Stage A dependency locks are no longer sufficient"

mkdir -p "$DEST/services/ai-bridge" "$DEST/services/ai-gateway" "$DEST/metadata"

echo "===== SOURCE ====="
say "release_id=$RELEASE_ID"
say "source_git_sha=$SOURCE_SHA"

# Both services come from the same exact committed source. Gateway code is
# byte-equivalent to the Stage A gateway source by the guard above.
git -C "$ROOT" archive "$SOURCE_SHA" | tar -x -C "$DEST/services/ai-bridge"
git -C "$ROOT" archive "$SOURCE_SHA" | tar -x -C "$DEST/services/ai-gateway"

cp -a "$ROOT/deploy/stage-a/locks" "$DEST/metadata/locks"

cat > "$DEST/metadata/release-manifest.yaml" <<MANIFEST
release:
  id: $RELEASE_ID
  stage: C
  source_git_sha: $SOURCE_SHA
  config_schema_version: 1
  migration_version: provider-abstraction-v1
  provider_model_config_version: qwen36-hermes64k-gpu-20260919-v1
  behavior_change: false

ai_bridge:
  source_git_sha: $SOURCE_SHA

ai_gateway:
  source_git_sha: $SOURCE_SHA
  scheduler_baseline_sha: $BASE_GATEWAY_SHA
  scheduler_source_changed: false

providers:
  llm: LLMProvider/OllamaAdapter
  agent: AgentProvider/HermesAdapter
  media: MediaGenerationProvider/ComfyUIAdapter
MANIFEST

echo "===== AI BRIDGE VENV ====="
python3.14 -m venv "$DEST/services/ai-bridge/.venv"
"$DEST/services/ai-bridge/.venv/bin/python" -m pip   --disable-pip-version-check install   -r "$ROOT/deploy/stage-a/locks/ai-bridge.requirements.txt"
"$DEST/services/ai-bridge/.venv/bin/python" -m pip   --disable-pip-version-check install   --no-deps "$DEST/services/ai-bridge"

echo "===== AI GATEWAY VENV ====="
python3.14 -m venv "$DEST/services/ai-gateway/.venv"
"$DEST/services/ai-gateway/.venv/bin/python" -m pip   --disable-pip-version-check install   -r "$ROOT/deploy/stage-a/locks/ai-gateway.requirements.txt"
"$DEST/services/ai-gateway/.venv/bin/python" -m pip   --disable-pip-version-check install   --no-deps "$DEST/services/ai-gateway"

cat > "$DEST/RELEASE" <<STAMP
release_id=$RELEASE_ID
stage=C
source_git_sha=$SOURCE_SHA
ai_bridge_git_sha=$SOURCE_SHA
ai_gateway_git_sha=$SOURCE_SHA
scheduler_baseline_sha=$BASE_GATEWAY_SHA
config_schema_version=1
migration_version=provider-abstraction-v1
provider_model_config_version=qwen36-hermes64k-gpu-20260919-v1
STAMP

echo "===== VERIFY IMPORTS ====="
"$DEST/services/ai-bridge/.venv/bin/python" - <<'PY'
from ai_bridge.providers.contracts import (
    LLMProvider,
    AgentProvider,
    MediaGenerationProvider,
)
from ai_bridge.providers.ollama import OllamaAdapter
from ai_bridge.providers.hermes import HermesAdapter
from ai_bridge.providers.comfyui import ComfyUIAdapter
print("AI BRIDGE PROVIDERS: PASS")
PY

"$DEST/services/ai-gateway/.venv/bin/python" - <<'PY'
from ai_bridge.gateway.app import app
print("AI GATEWAY: PASS")
PY

echo "===== VERIFY STAGE30 IMPORT ====="
"$DEST/services/ai-bridge/.venv/bin/python"   "$DEST/services/ai-bridge/tools/local_video/generate_ltx23_stage30.py"   --help >/dev/null
say "STAGE30 IMPORT: PASS"

echo "===== CHECKSUMS ====="
(
  cd "$DEST"
  find . -type f ! -path './metadata/SHA256SUMS' -print0     | sort -z     | xargs -0 sha256sum     > metadata/SHA256SUMS
)

echo
say "Built Stage C release: $DEST"
cat "$DEST/RELEASE"
