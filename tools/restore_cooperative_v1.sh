#!/usr/bin/env bash
set -euo pipefail
exec python3 "$(dirname "$(readlink -f "$0")")/restore_cooperative_v1.py" "$@"
