#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd -P)"
exec env RELEASE_STAGE=M RELEASE_MIGRATION=crt-projection-v1 \
  RELEASE_OBSERVABILITY_CONTRACT=1 RELEASE_KNOWLEDGE_CONTRACT=1 \
  RELEASE_CRT_CONTRACT=1 RELEASE_ERS_CONTRACT=1 RELEASE_MIGRATION_TOOLING=1 \
  RELEASE_EXTRA_REQUIREMENTS="$ROOT/deploy/stage-l/locks/migration.requirements.txt" \
  bash "$ROOT/deploy/runtime/build_release.sh" "$@"
