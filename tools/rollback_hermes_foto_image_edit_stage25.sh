#!/usr/bin/env bash
set -euo pipefail

HERMES_HOME="/srv/ai-data/hermes"
HERMES_SOURCE="${HERMES_HOME}/hermes-agent"
HERMES_RUN="${HERMES_SOURCE}/gateway/run.py"
HERMES_STATE="${HERMES_HOME}/gateway_state.json"
HERMES_PYTHON="${HERMES_SOURCE}/venv/bin/python"
SKILL_DEST="${HERMES_HOME}/skills/foto/SKILL.md"
EDIT_DEST="/usr/local/bin/generate-image-edit"
EDIT_TG_DEST="/usr/local/bin/generate-image-edit-telegram"
BACKUP_DIR="${HERMES_HOME}/stage25-foto-edit-backup"
PATCH_BEGIN="# AI_SERVER_STAGE25_FOTO_MEDIA_PATH_BEGIN"

say() { printf '%s\n' "$*"; }
section() { printf '\n===== %s =====\n' "$1"; }
fail() { say "FAIL: $*"; exit 1; }

section "ROLLBACK STAGE-25 /FOTO IMAGE EDIT"
[ -d "$BACKUP_DIR" ] || fail "backup missing: $BACKUP_DIR"
[ -r "$BACKUP_DIR/run.py" ] || fail "run.py backup missing"
[ -r "$BACKUP_DIR/SKILL.md" ] || fail "SKILL.md backup missing"

section "RESTORE HERMES RUN.PY + /FOTO SKILL"
cp --preserve=mode,timestamps "$BACKUP_DIR/run.py" "$HERMES_RUN"
install -m 0644 "$BACKUP_DIR/SKILL.md" "$SKILL_DEST"
"$HERMES_PYTHON" -m py_compile "$HERMES_RUN"
if grep -Fq "$PATCH_BEGIN" "$HERMES_RUN"; then
    fail "Stage25 marker still present after run.py restore"
fi
say "PASS: Hermes source and /foto skill restored"

section "RESTORE LOCAL WRAPPERS"
if [ -f "$BACKUP_DIR/generate-image-edit.ABSENT" ]; then
    sudo rm -f "$EDIT_DEST"
    say "PASS: removed Stage25-only $EDIT_DEST"
elif [ -r "$BACKUP_DIR/generate-image-edit" ]; then
    sudo install -m 0755 "$BACKUP_DIR/generate-image-edit" "$EDIT_DEST"
    say "PASS: restored previous $EDIT_DEST"
else
    fail "no rollback state for $EDIT_DEST"
fi

if [ -f "$BACKUP_DIR/generate-image-edit-telegram.ABSENT" ]; then
    sudo rm -f "$EDIT_TG_DEST"
    say "PASS: removed Stage25-only $EDIT_TG_DEST"
elif [ -r "$BACKUP_DIR/generate-image-edit-telegram" ]; then
    sudo install -m 0755 "$BACKUP_DIR/generate-image-edit-telegram" "$EDIT_TG_DEST"
    say "PASS: restored previous $EDIT_TG_DEST"
else
    fail "no rollback state for $EDIT_TG_DEST"
fi

section "RESTART HERMES"
systemctl --user restart hermes-gateway.service
[ "$(systemctl --user is-active hermes-gateway.service 2>/dev/null || true)" = "active" ] || fail "Hermes failed to restart"

"$HERMES_PYTHON" - "$HERMES_STATE" <<'PY'
from pathlib import Path
import json, sys, time
path = Path(sys.argv[1]); deadline = time.monotonic() + 90; last = None
while time.monotonic() < deadline:
    try: state = json.loads(path.read_text(encoding="utf-8"))
    except Exception: time.sleep(1); continue
    last = state; platforms = state.get("platforms") or {}
    if (state.get("gateway_state") == "running"
            and (platforms.get("telegram") or {}).get("state") == "connected"
            and (platforms.get("api_server") or {}).get("state") == "connected"):
        print("PASS: Hermes gateway running, Telegram connected, API connected")
        break
    time.sleep(1)
else:
    print(json.dumps(last, ensure_ascii=False, indent=2) if last else "<no gateway state>")
    raise SystemExit("FAIL: Hermes did not reconnect within 90s")
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
say "PASS: Stage-25 rollback completed"
say "The previously working Stage-23 text-to-image /foto state is restored."
