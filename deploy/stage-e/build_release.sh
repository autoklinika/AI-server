#!/usr/bin/env bash
set -euo pipefail

DEST="${1:?usage: $0 DEST RELEASE_ID}"
RELEASE_ID="${2:?usage: $0 DEST RELEASE_ID}"
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd -P)"
PYTHON_BIN="${PYTHON_BIN:-python3.14}"

OWNER_UID="$(stat -c '%u' "$ROOT")"
OWNER_NAME="$(getent passwd "$OWNER_UID" | cut -d: -f1)"
OWNER_HOME="$(getent passwd "$OWNER_UID" | cut -d: -f6)"
[[ -n "$OWNER_NAME" && "$OWNER_HOME" == /* ]] || {
  echo "FAIL: cannot resolve repository owner" >&2
  exit 2
}

ugit() {
  runuser -u "$OWNER_NAME" -- env     HOME="$OWNER_HOME"     PATH="/usr/local/bin:/usr/bin:/bin"     git "$@"
}

HEAD_SHA="$(ugit -C "$ROOT" rev-parse HEAD)"
SOURCE_SHA="${STAGE_E_SOURCE_SHA:-$HEAD_SHA}"
[[ "$SOURCE_SHA" == "$HEAD_SHA" ]] || {
  echo "FAIL: Stage E source SHA does not match worktree HEAD" >&2
  exit 2
}

say(){ printf '%s\n' "$*"; }
fail(){ say "FAIL: $*" >&2; exit 1; }

[[ -z "$(ugit -C "$ROOT" status --porcelain)" ]] || fail "working tree must be clean"
[[ "$RELEASE_ID" =~ ^stage-e-[a-f0-9]{12}$ ]] || fail "invalid Stage E release id"
[[ ! -e "$DEST" ]] || fail "destination already exists: $DEST"
ugit -C "$ROOT" cat-file -e "$SOURCE_SHA^{commit}" || fail "invalid source commit"

# Stage E intentionally permits Resource Manager / Gateway source changes.
# Dependency locks remain explicit release inputs and must be updated deliberately.

mkdir -p "$DEST/services/ai-bridge" "$DEST/services/ai-gateway" "$DEST/metadata"

echo "===== SOURCE ====="
say "release_id=$RELEASE_ID"
say "source_git_sha=$SOURCE_SHA"

# Both services come from the same exact committed source. Stage E permits
# Gateway / Resource Manager changes and records them in the release SHA.
ugit -C "$ROOT" archive "$SOURCE_SHA" | tar -x -C "$DEST/services/ai-bridge"
ugit -C "$ROOT" archive "$SOURCE_SHA" | tar -x -C "$DEST/services/ai-gateway"

cp -a "$ROOT/deploy/stage-a/locks" "$DEST/metadata/locks"

cat > "$DEST/metadata/release-manifest.yaml" <<MANIFEST
release:
  id: $RELEASE_ID
  stage: E
  phase: E
  source_git_sha: $SOURCE_SHA
  config_schema_version: 4
  migration_version: platform-api-v1
  provider_model_config_version: qwen36-hermes64k-gpu-20260919-v1
  changed_components:
    - ai-bridge
    - ai-gateway
    - deployment
    - desired-state
  contract_versions:
    platform_api: 1
    resource_manager: 2
    priority_class: 1
    job_state: 1
    unified_admission: 1
    compatibility: 1
    llm_provider: 1
    agent_provider: 1
    media_generation_provider: 1
    embedding_provider: 1
    knowledge_backend: 1
  schema_versions:
    provider_registry: 1
  compatibility:
    analysis_direct_ollama_recovery: true
    legacy_gateway_priority_headers: true
    legacy_gateway_client_endpoints: true

ai_bridge:
  source_git_sha: $SOURCE_SHA

ai_gateway:
  source_git_sha: $SOURCE_SHA

provider_model_config:
  llm_provider: OllamaAdapter
  llm_model: qwen3.6:35b
  agent_provider: HermesAdapter
  media_provider: ComfyUIAdapter
  embedding_provider: contract-only
  knowledge_backend: contract-only
MANIFEST

echo "===== AI BRIDGE VENV ====="
"$PYTHON_BIN" -m venv "$DEST/services/ai-bridge/.venv"
"$DEST/services/ai-bridge/.venv/bin/python" -m pip   --disable-pip-version-check install   -r "$ROOT/deploy/stage-a/locks/ai-bridge.requirements.txt"
"$DEST/services/ai-bridge/.venv/bin/python" -m pip   --disable-pip-version-check install   --no-deps "$DEST/services/ai-bridge"

echo "===== AI GATEWAY VENV ====="
"$PYTHON_BIN" -m venv "$DEST/services/ai-gateway/.venv"
"$DEST/services/ai-gateway/.venv/bin/python" -m pip   --disable-pip-version-check install   -r "$ROOT/deploy/stage-a/locks/ai-gateway.requirements.txt"
"$DEST/services/ai-gateway/.venv/bin/python" -m pip   --disable-pip-version-check install   --no-deps "$DEST/services/ai-gateway"

cat > "$DEST/RELEASE" <<STAMP
release_id=$RELEASE_ID
stage=E
phase=E
source_git_sha=$SOURCE_SHA
ai_bridge_git_sha=$SOURCE_SHA
ai_gateway_git_sha=$SOURCE_SHA
config_schema_version=4
migration_version=platform-api-v1
platform_api_contract_version=1
resource_manager_contract_version=2
priority_class_contract_version=1
job_state_contract_version=1
provider_registry_schema_version=1
unified_admission_contract_version=1
compatibility_contract_version=1
provider_model_config_version=qwen36-hermes64k-gpu-20260919-v1
STAMP

python3 "$ROOT/deploy/stage-e/validate_release_metadata.py" "$DEST"

echo "===== VERIFY IMPORTS ====="
"$DEST/services/ai-bridge/.venv/bin/python" - <<'PY'
from ai_bridge.providers.contracts import (
    LLMProvider,
    AgentProvider,
    MediaGenerationProvider,
    EmbeddingProvider,
    KnowledgeBackend,
)
from ai_bridge.providers.ollama import OllamaAdapter
from ai_bridge.providers.hermes import HermesAdapter
from ai_bridge.providers.comfyui import ComfyUIAdapter
print("AI BRIDGE PROVIDER CONTRACTS: PASS")
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
say "Built Stage E release: $DEST"
cat "$DEST/RELEASE"
