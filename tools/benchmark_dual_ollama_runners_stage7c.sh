#!/usr/bin/env bash
set -euo pipefail

ROOT="${HOME}/AI-server"
BRANCH="feat/ai-gateway-scheduler"
SOURCE="tools/benchmark_dual_ollama_runners_stage7.sh"
TMP="$(mktemp /tmp/ai-gateway-stage7c.XXXXXX.sh)"

cleanup() {
    rm -f "$TMP"
}
trap cleanup EXIT INT TERM

[ -d "$ROOT/.git" ] || { echo "FAIL: repository missing at $ROOT"; exit 1; }

cd "$ROOT"
git show "origin/${BRANCH}:${SOURCE}" > "$TMP"

python3 - "$TMP" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
text = path.read_text(encoding="utf-8")

old_mem = '''mem_available_gib() {
    awk '/^MemAvailable:/ {printf "%.2f", $2/1024/1024}' /proc/meminfo
}
'''
new_mem = '''mem_available_gib() {
    LC_ALL=C awk '/^MemAvailable:/ {printf "%.2f", $2/1024/1024}' /proc/meminfo
}
'''
if old_mem not in text:
    raise SystemExit("FAIL: expected Stage-7 mem_available_gib block not found")
text = text.replace(old_mem, new_mem, 1)

old_validation = '''PRIMARY_CMD="$(ps -eo args | grep '[l]lama-server' | head -n 1 || true)"
case " $PRIMARY_CMD " in
  *" -c ${CONTEXT} "*" -np 1 "*) say "PASS: primary runner is -c $CONTEXT -np 1" ;;
  *) say "FAIL: primary runner is not 32k/np1"; say "$PRIMARY_CMD"; exit 1 ;;
esac
'''
new_validation = '''PRIMARY_CMD="$(ps -eo args | grep '[l]lama-server' | head -n 1 || true)"
if printf '%s\\n' "$PRIMARY_CMD" | grep -Fq -- "-c ${CONTEXT}" \\
   && printf '%s\\n' "$PRIMARY_CMD" | grep -Fq -- "-np 1"; then
    say "PASS: primary runner is -c $CONTEXT -np 1"
else
    say "FAIL: primary runner is not 32k/np1"
    say "$PRIMARY_CMD"
    exit 1
fi
'''
if old_validation not in text:
    raise SystemExit("FAIL: expected Stage-7 primary runner validation block not found")
text = text.replace(old_validation, new_validation, 1)

path.write_text(text, encoding="utf-8")
PY

bash -n "$TMP"

echo "===== STAGE-7C LOCALE + RUNNER VALIDATION FIX ====="
echo "PASS: patched only machine-number locale and primary runner validation"
echo "Starting the unchanged reversible dual-runner benchmark..."
echo

bash "$TMP"
