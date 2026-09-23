#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd -P)"
exec env RELEASE_STAGE=G RELEASE_MIGRATION=wvc-domain-v1 bash "$ROOT/deploy/runtime/build_release.sh" "$@"
