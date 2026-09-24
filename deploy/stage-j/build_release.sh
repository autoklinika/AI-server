#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd -P)"
exec env RELEASE_STAGE=J RELEASE_MIGRATION=knowledge-service-v1 \
  RELEASE_OBSERVABILITY_CONTRACT=1 RELEASE_KNOWLEDGE_CONTRACT=1 \
  bash "$ROOT/deploy/runtime/build_release.sh" "$@"
