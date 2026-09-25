#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if [[ "$EUID" -ne 0 ]]; then
  exec sudo -n bash "$0" "$@"
fi
if python3 -B "$SCRIPT_DIR/gate.py" 40_rollback; then
  exit 0
fi
exec python3 -B "$SCRIPT_DIR/emergency_recover.py"
