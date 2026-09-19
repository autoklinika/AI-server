#!/usr/bin/env bash
set -euo pipefail

DEST="${1:?usage: $0 DEST}"
ROOT="$(git rev-parse --show-toplevel)"
RELEASE_ID="stage-a-baseline-20260919-r1"
GATEWAY_SHA="0e53bbc6f2fad703c46e00526d1bbecedb378438"

rm -rf "$DEST"
mkdir -p "$DEST/services" "$DEST/metadata"

# Exact production AI Bridge reconstruction.
"$ROOT/deploy/stage-a/reconstruct_ai_bridge_baseline.sh" \
  "$DEST/services/ai-bridge"

# Exact production AI Gateway source.
mkdir -p "$DEST/services/ai-gateway"
git -C "$ROOT" archive "$GATEWAY_SHA" | \
  tar -x -C "$DEST/services/ai-gateway"

# Release metadata / dependency locks.
cp "$ROOT/deploy/stage-a/release-baseline.yaml" \
   "$DEST/metadata/release-manifest.yaml"

cp -a "$ROOT/deploy/stage-a/locks" \
   "$DEST/metadata/locks"

cat > "$DEST/RELEASE" <<STAMP
release_id=$RELEASE_ID
recipe_git_sha=$(git -C "$ROOT" rev-parse HEAD)
ai_gateway_git_sha=$GATEWAY_SHA
config_schema_version=1
migration_version=legacy-pre-platform-v1
provider_model_config_version=qwen36-hermes64k-gpu-20260919-v1
STAMP

find "$DEST" -type f -print0 | sort -z | \
  xargs -0 sha256sum > "$DEST/metadata/SHA256SUMS"

echo "Built release: $DEST"
cat "$DEST/RELEASE"
