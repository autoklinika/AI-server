#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd -P)"
exec env RELEASE_STAGE=I RELEASE_MIGRATION=observability-v1 RELEASE_OBSERVABILITY_CONTRACT=1 \
  bash "$ROOT/deploy/runtime/build_release.sh" "$@"
