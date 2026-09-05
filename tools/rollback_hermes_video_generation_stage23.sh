#!/usr/bin/env bash
set -euo pipefail

HERMES_HOME="/srv/ai-data/hermes"
HERMES_SOURCE="${HERMES_HOME}/hermes-agent"
HERMES_PYTHON="${HERMES_SOURCE}/venv/bin/python"
HERMES_CONFIG="${HERMES_HOME}/config.yaml"
STATE_FILE="${HERMES_HOME}/gateway_state.json"
CONFIG_BACKUP="${HERMES_HOME}/config.yaml.pre-video-gen-stage23"
CURRENT_SNAPSHOT="${HERMES_HOME}/config.yaml.pre-stage23-rollback-current"
ENV_FILE="${HERMES_HOME}/video-gen.env"
ENV_BACKUP="${HERMES_HOME}/video-gen.env.pre-video-gen-stage23"
ENV_ABSENT_MARKER="${HERMES_HOME}/.video-gen-env-absent-pre-stage23"
DROPIN_DIR="${HOME}/.config/systemd/user/hermes-gateway.service.d"
DROPIN_FILE="${DROPIN_DIR}/30-video-gen.conf"
DROPIN_BACKUP="${DROPIN_FILE}.pre-video-gen-stage23"
DROPIN_ABSENT_MARKER="${HERMES_HOME}/.video-gen-dropin-absent-pre-stage23"

say() { printf '%s\n' "$*"; }
section() { printf '\n===== %s =====\n' "$1"; }

[ -x "$HERMES_PYTHON" ] || { say "FAIL: Hermes Python missing: $HERMES_PYTHON"; exit 1; }
[ -r "$HERMES_CONFIG" ] || { say "FAIL: Hermes config missing: $HERMES_CONFIG"; exit 1; }
[ -r "$CONFIG_BACKUP" ] || { say "FAIL: Stage-23 config backup missing: $CONFIG_BACKUP"; exit 1; }

section "STAGE-23 HERMES VIDEO GENERATION ROLLBACK"
say "Restoring pre-Stage-23 Hermes config and service environment."

section "SNAPSHOT CURRENT CONFIG"
cp --preserve=mode,timestamps "$HERMES_CONFIG" "$CURRENT_SNAPSHOT"
say "PASS: saved current config to $CURRENT_SNAPSHOT"

section "ATOMIC CONFIG RESTORE"
"$HERMES_PYTHON" - "$HERMES_CONFIG" "$CONFIG_BACKUP" <<'PY'
from pathlib import Path
import os, shutil, sys, tempfile, yaml
live = Path(sys.argv[1])
backup = Path(sys.argv[2])
cfg = yaml.safe_load(backup.read_text(encoding="utf-8")) or {}
if not isinstance(cfg, dict):
    raise SystemExit("FAIL: Stage-23 backup is not a YAML mapping")
fd, tmp = tempfile.mkstemp(prefix=live.name + ".stage23-rollback.", dir=str(live.parent))
os.close(fd)
try:
    shutil.copyfile(backup, tmp)
    os.chmod(tmp, live.stat().st_mode)
    with open(tmp, "rb") as f:
        os.fsync(f.fileno())
    os.replace(tmp, live)
finally:
    try:
        os.unlink(tmp)
    except FileNotFoundError:
        pass
print("PASS: restored pre-Stage-23 Hermes config atomically")
PY

section "RESTORE VIDEO CREDENTIAL ENV"
if [ -r "$ENV_BACKUP" ]; then
    cp --preserve=mode,timestamps "$ENV_BACKUP" "$ENV_FILE"
    say "PASS: restored pre-Stage-23 video env"
elif [ -e "$ENV_ABSENT_MARKER" ]; then
    rm -f "$ENV_FILE"
    say "PASS: removed Stage-23 video env (none existed before cutover)"
else
    say "WARN: no env backup/absence marker; leaving $ENV_FILE unchanged"
fi

section "RESTORE USER SYSTEMD DROP-IN"
if [ -r "$DROPIN_BACKUP" ]; then
    mkdir -p "$DROPIN_DIR"
    cp --preserve=mode,timestamps "$DROPIN_BACKUP" "$DROPIN_FILE"
    say "PASS: restored pre-Stage-23 systemd drop-in"
elif [ -e "$DROPIN_ABSENT_MARKER" ]; then
    rm -f "$DROPIN_FILE"
    say "PASS: removed Stage-23 systemd drop-in (none existed before cutover)"
else
    say "WARN: no drop-in backup/absence marker; leaving $DROPIN_FILE unchanged"
fi
systemctl --user daemon-reload

section "VALIDATE CONFIG RESTORE"
"$HERMES_PYTHON" - "$HERMES_CONFIG" "$CONFIG_BACKUP" <<'PY'
from pathlib import Path
import hashlib, sys, yaml

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()
live_sha = sha(sys.argv[1])
backup_sha = sha(sys.argv[2])
print("live sha256:  ", live_sha)
print("backup sha256:", backup_sha)
if live_sha != backup_sha:
    raise SystemExit("FAIL: restored config does not byte-match Stage-23 backup")
cfg = yaml.safe_load(Path(sys.argv[1]).read_text(encoding="utf-8")) or {}
platform = cfg.get("platform_toolsets") or {}
print("restored platform_toolsets.telegram:", repr(platform.get("telegram") if isinstance(platform, dict) else None))
print("restored video_gen:", repr(cfg.get("video_gen")))
print("PASS: config restore verified")
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
if [ "$(systemctl is-active ai-gateway.service 2>/dev/null || true)" = "active" ]; then
    "$HERMES_PYTHON" - <<'PY'
import json, urllib.request
with urllib.request.urlopen("http://127.0.0.1:11435/health", timeout=3) as r:
    h = json.load(r)
assert h.get("status") == "ok" and h.get("ollama") == "ok", h
print("PASS: AI Gateway healthy")
PY
else
    say "WARN: ai-gateway.service is not active; skipped Gateway health postcheck"
fi

section "DONE"
say "PASS: Stage-23 rollback completed"
say "Pre-Stage-23 Hermes configuration and service environment were restored."
say "Original config backup retained: $CONFIG_BACKUP"
say "Cutover config snapshot retained: $CURRENT_SNAPSHOT"
