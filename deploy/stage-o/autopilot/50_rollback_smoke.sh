#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if [[ "$EUID" -eq 0 ]]; then
  exec python3 -B "$SCRIPT_DIR/gate.py" 50_rollback_smoke
fi
exec sudo -n python3 -B "$SCRIPT_DIR/gate.py" 50_rollback_smoke
