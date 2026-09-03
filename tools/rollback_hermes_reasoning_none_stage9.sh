#!/usr/bin/env bash
set -euo pipefail

HERMES_HOME="/srv/ai-data/hermes"
HERMES_CONFIG="${HERMES_HOME}/config.yaml"
BACKUP="${HERMES_CONFIG}.pre-reasoning-none-stage9"
HERMES_PYTHON="${HERMES_HOME}/hermes-agent/venv/bin/python"

say() { printf '%s\n' "$*"; }
section() { printf '\n===== %s =====\n' "$1"; }

[ -x "$HERMES_PYTHON" ] || { say "FAIL: Hermes Python missing: $HERMES_PYTHON"; exit 1; }
[ -r "$BACKUP" ] || { say "FAIL: Stage-9 backup missing: $BACKUP"; exit 1; }

section "ROLLBACK HERMES REASONING-OFF STAGE-9"
cp -a "$BACKUP" "$HERMES_CONFIG"
say "PASS: restored Hermes config from $BACKUP"

systemctl --user restart hermes-gateway.service
for _ in $(seq 1 60); do
    if [ "$(systemctl --user is-active hermes-gateway.service 2>/dev/null || true)" = "active" ]; then
        break
    fi
    sleep 0.5
done
[ "$(systemctl --user is-active hermes-gateway.service 2>/dev/null || true)" = "active" ] || {
    say "FAIL: Hermes did not return active"
    exit 1
}

"$HERMES_PYTHON" - "$HERMES_CONFIG" <<'PY'
from pathlib import Path
import sys, yaml
cfg = yaml.safe_load(Path(sys.argv[1]).read_text(encoding="utf-8")) or {}
print("restored agent.reasoning_effort:", repr((cfg.get("agent") or {}).get("reasoning_effort")))
PY

"$HERMES_PYTHON" - <<'PY'
import json, urllib.request
with urllib.request.urlopen("http://127.0.0.1:11435/health", timeout=2) as r:
    h = json.load(r)
assert h.get("status") == "ok" and h.get("ollama") == "ok", h
print("PASS: AI Gateway healthy")
PY

say "PASS: Stage-9 Hermes reasoning setting rolled back"
