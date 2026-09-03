#!/usr/bin/env bash
set -euo pipefail

HERMES_HOME="/srv/ai-data/hermes"
HERMES_SOURCE="${HERMES_HOME}/hermes-agent"
HERMES_PYTHON="${HERMES_SOURCE}/venv/bin/python"
HERMES_CONFIG="${HERMES_HOME}/config.yaml"
STATE_FILE="${HERMES_HOME}/gateway_state.json"
BACKUP="${HERMES_HOME}/config.yaml.pre-telegram-static-stage22"
CURRENT_SNAPSHOT="${HERMES_HOME}/config.yaml.pre-stage22-rollback-current"

say() { printf '%s\n' "$*"; }
section() { printf '\n===== %s =====\n' "$1"; }

[ -x "$HERMES_PYTHON" ] || { say "FAIL: Hermes Python missing: $HERMES_PYTHON"; exit 1; }
[ -r "$HERMES_CONFIG" ] || { say "FAIL: Hermes config missing: $HERMES_CONFIG"; exit 1; }
[ -r "$BACKUP" ] || { say "FAIL: Stage-22 backup missing or unreadable: $BACKUP"; exit 1; }
[ "$(systemctl is-active ai-gateway.service 2>/dev/null || true)" = "active" ] || { say "FAIL: ai-gateway.service is not active"; exit 1; }
[ "$(systemctl is-active ollama.service 2>/dev/null || true)" = "active" ] || { say "FAIL: ollama.service is not active"; exit 1; }

section "STAGE-22 TELEGRAM STATIC PROFILE ROLLBACK"
say "Restoring Hermes configuration from: $BACKUP"

section "CURRENT STATE"
"$HERMES_PYTHON" - "$HERMES_CONFIG" "$BACKUP" <<'PY'
from pathlib import Path
import sys, yaml
for label, name in (("current", sys.argv[1]), ("backup", sys.argv[2])):
    cfg = yaml.safe_load(Path(name).read_text(encoding="utf-8")) or {}
    platform = cfg.get("platform_toolsets") or {}
    telegram = platform.get("telegram") if isinstance(platform, dict) else None
    reasoning = (cfg.get("agent") or {}).get("reasoning_effort")
    print(f"{label} platform_toolsets.telegram:", repr(telegram))
    print(f"{label} agent.reasoning_effort:", repr(reasoning))
PY

section "SNAPSHOT CURRENT CUTOVER CONFIG"
cp --preserve=mode,timestamps "$HERMES_CONFIG" "$CURRENT_SNAPSHOT"
say "PASS: saved current config to $CURRENT_SNAPSHOT"

section "ATOMIC RESTORE"
"$HERMES_PYTHON" - "$HERMES_CONFIG" "$BACKUP" <<'PY'
from pathlib import Path
import os, shutil, sys, tempfile, yaml

target = Path(sys.argv[1])
backup = Path(sys.argv[2])
# Parse before restoring so a corrupt backup can never replace the live config.
cfg = yaml.safe_load(backup.read_text(encoding="utf-8")) or {}
if not isinstance(cfg, dict):
    raise SystemExit("FAIL: Stage-22 backup is not a YAML mapping")

fd, tmp_name = tempfile.mkstemp(prefix=target.name + ".stage22-rollback.", dir=str(target.parent))
os.close(fd)
try:
    shutil.copyfile(backup, tmp_name)
    os.chmod(tmp_name, target.stat().st_mode)
    with open(tmp_name, "rb") as f:
        os.fsync(f.fileno())
    os.replace(tmp_name, target)
finally:
    try:
        os.unlink(tmp_name)
    except FileNotFoundError:
        pass
print("PASS: restored pre-Stage-22 config atomically")
PY

section "VALIDATE RESTORE"
"$HERMES_PYTHON" - "$HERMES_CONFIG" "$BACKUP" <<'PY'
from pathlib import Path
import hashlib, sys, yaml

def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

live_sha = digest(sys.argv[1])
backup_sha = digest(sys.argv[2])
print("live sha256:  ", live_sha)
print("backup sha256:", backup_sha)
if live_sha != backup_sha:
    raise SystemExit("FAIL: restored config does not byte-match backup")
cfg = yaml.safe_load(Path(sys.argv[1]).read_text(encoding="utf-8")) or {}
platform = cfg.get("platform_toolsets") or {}
print("restored platform_toolsets.telegram:", repr(platform.get("telegram") if isinstance(platform, dict) else None))
print("restored agent.reasoning_effort:", repr((cfg.get("agent") or {}).get("reasoning_effort")))
print("PASS: restored config matches Stage-22 backup exactly")
PY

section "RESTART HERMES"
systemctl --user restart hermes-gateway.service
[ "$(systemctl --user is-active hermes-gateway.service 2>/dev/null || true)" = "active" ] || { say "FAIL: hermes-gateway.service did not become active"; exit 1; }
say "PASS: Hermes service active"

section "WAIT FOR TELEGRAM + API"
"$HERMES_PYTHON" - "$STATE_FILE" <<'PY'
from pathlib import Path
import json, sys, time
path = Path(sys.argv[1])
deadline = time.monotonic() + 90
last = None
while time.monotonic() < deadline:
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        time.sleep(1)
        continue
    last = state
    platforms = state.get("platforms") or {}
    if (
        state.get("gateway_state") == "running"
        and (platforms.get("telegram") or {}).get("state") == "connected"
        and (platforms.get("api_server") or {}).get("state") == "connected"
    ):
        print("PASS: Hermes gateway running, Telegram connected, API connected")
        break
    time.sleep(1)
else:
    print(json.dumps(last, ensure_ascii=False, indent=2) if last else "<no readable gateway_state>")
    raise SystemExit("FAIL: Hermes did not fully reconnect within 90 s")
PY

section "POSTCHECK"
"$HERMES_PYTHON" - <<'PY'
import json, urllib.request
with urllib.request.urlopen("http://127.0.0.1:11435/health", timeout=3) as r:
    h = json.load(r)
assert h.get("status") == "ok" and h.get("ollama") == "ok", h
print("PASS: AI Gateway healthy")
PY

section "DONE"
say "PASS: Stage-22 rollback completed"
say "Pre-Stage-22 Hermes configuration is restored."
say "Original backup retained: $BACKUP"
say "Cutover config snapshot retained: $CURRENT_SNAPSHOT"
