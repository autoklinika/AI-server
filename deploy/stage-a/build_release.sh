#!/usr/bin/env bash
set -euo pipefail

DEST="${1:?usage: $0 DEST [RELEASE_ID]}"
RELEASE_ID="${2:-$(basename "$DEST")}"
ROOT="$(git rev-parse --show-toplevel)"
GATEWAY_SHA="0e53bbc6f2fad703c46e00526d1bbecedb378438"

rm -rf "$DEST"
mkdir -p "$DEST/services" "$DEST/metadata"

echo "===== SOURCE ====="

"$ROOT/deploy/stage-a/reconstruct_ai_bridge_baseline.sh" \
  "$DEST/services/ai-bridge"

mkdir -p "$DEST/services/ai-gateway"
git -C "$ROOT" archive "$GATEWAY_SHA" \
  | tar -x -C "$DEST/services/ai-gateway"

cp "$ROOT/deploy/stage-a/release-baseline.yaml" \
   "$DEST/metadata/release-manifest.yaml"

cp -a "$ROOT/deploy/stage-a/locks" \
   "$DEST/metadata/locks"

echo "===== AI BRIDGE VENV ====="

python3.14 -m venv "$DEST/services/ai-bridge/.venv"

"$DEST/services/ai-bridge/.venv/bin/python" -m pip \
  --disable-pip-version-check install \
  -r "$ROOT/deploy/stage-a/locks/ai-bridge.requirements.txt"

"$DEST/services/ai-bridge/.venv/bin/python" -m pip \
  --disable-pip-version-check install \
  --no-deps "$DEST/services/ai-bridge"

echo "===== AI GATEWAY VENV ====="

python3.14 -m venv "$DEST/services/ai-gateway/.venv"

"$DEST/services/ai-gateway/.venv/bin/python" -m pip \
  --disable-pip-version-check install \
  -r "$ROOT/deploy/stage-a/locks/ai-gateway.requirements.txt"

"$DEST/services/ai-gateway/.venv/bin/python" -m pip \
  --disable-pip-version-check install \
  --no-deps "$DEST/services/ai-gateway"

cat > "$DEST/RELEASE" <<STAMP
release_id=$RELEASE_ID
recipe_git_sha=$(git -C "$ROOT" rev-parse HEAD)
ai_gateway_git_sha=$GATEWAY_SHA
config_schema_version=1
migration_version=legacy-pre-platform-v1
provider_model_config_version=qwen36-hermes64k-gpu-20260919-v1
STAMP

echo "===== VERIFY IMPORTS ====="

"$DEST/services/ai-bridge/.venv/bin/python" -c \
  "import ai_bridge; print('AI BRIDGE: PASS')"

"$DEST/services/ai-gateway/.venv/bin/python" -c \
  "from ai_bridge.gateway.app import app; print('AI GATEWAY: PASS')"

echo "===== CHECKSUMS ====="

find "$DEST" -type f \
  ! -path "$DEST/metadata/SHA256SUMS" \
  -print0 \
  | sort -z \
  | xargs -0 sha256sum \
  > "$DEST/metadata/SHA256SUMS"

echo
echo "Built release: $DEST"
cat "$DEST/RELEASE"
