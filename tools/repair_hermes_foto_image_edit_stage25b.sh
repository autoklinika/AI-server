#!/usr/bin/env bash
set -euo pipefail

AI_REPO="${AI_SERVER_REPO:-$HOME/AI-server}"
SOURCE_REF="${AI_SERVER_SOURCE_REF:-origin/feat/hermes-telegram-foto}"

HERMES_HOME="/srv/ai-data/hermes"
HERMES_SOURCE="${HERMES_HOME}/hermes-agent"
HERMES_PYTHON="${HERMES_SOURCE}/venv/bin/python"
HERMES_RUN="${HERMES_SOURCE}/gateway/run.py"
HERMES_CONFIG="${HERMES_HOME}/config.yaml"
HERMES_STATE="${HERMES_HOME}/gateway_state.json"
HERMES_EXPECTED_SHA="254158f4530cada634c4ef8f4cff93257c5b4f77"

SKILL_SOURCE="deploy/hermes/skills/foto/SKILL.md"
EDIT_SOURCE="deploy/local-bin/generate-image-edit"
EDIT_TG_SOURCE="deploy/local-bin/generate-image-edit-telegram"
PATCHER_SOURCE="tools/patch_hermes_foto_media_path_stage25.py"
SKILL_DEST="${HERMES_HOME}/skills/foto/SKILL.md"
EDIT_DEST="/usr/local/bin/generate-image-edit"
EDIT_TG_DEST="/usr/local/bin/generate-image-edit-telegram"

BACKUP_DIR="${HERMES_HOME}/stage25-foto-edit-backup"
PATCH_BEGIN="# AI_SERVER_STAGE25_FOTO_MEDIA_PATH_BEGIN"
PATCH_END="# AI_SERVER_STAGE25_FOTO_MEDIA_PATH_END"

say() { printf '%s\n' "$*"; }
section() { printf '\n===== %s =====\n' "$1"; }
fail() { say "FAIL: $*"; exit 1; }

section "STAGE-25B /FOTO IMAGE EDIT REPAIR"
say "Repairs the Stage-25 partial install that stopped on duplicate raw Hermes anchors."
say "Keeps the original Stage-25 rollback backup unchanged."
say "Selects the slash-skill patch point semantically via build_skill_invocation_message(cmd_key, user_instruction, ...)."
say "No newest-file heuristic; image path still comes from the same inbound Telegram event."

section "PRECHECK"
[ -d "$AI_REPO/.git" ] || fail "AI-server repo missing: $AI_REPO"
[ -d "$HERMES_SOURCE/.git" ] || fail "Hermes source missing: $HERMES_SOURCE"
[ -x "$HERMES_PYTHON" ] || fail "Hermes Python missing: $HERMES_PYTHON"
[ -r "$HERMES_RUN" ] || fail "Hermes gateway/run.py missing"
[ -r "$HERMES_CONFIG" ] || fail "Hermes config missing"
[ -d "$BACKUP_DIR" ] || fail "Stage25 backup directory missing: $BACKUP_DIR"
[ -r "$BACKUP_DIR/run.py" ] || fail "Stage25 backup run.py missing"
[ -r "$BACKUP_DIR/SKILL.md" ] || fail "Stage25 backup SKILL.md missing"
[ "$(systemctl is-active ai-gateway.service 2>/dev/null || true)" = "active" ] || fail "ai-gateway.service is not active"
[ "$(systemctl is-active ollama.service 2>/dev/null || true)" = "active" ] || fail "ollama.service is not active"
[ "$(systemctl is-active comfyui.service 2>/dev/null || true)" = "active" ] || fail "comfyui.service is not active"
[ "$(systemctl --user is-active hermes-gateway.service 2>/dev/null || true)" = "active" ] || fail "hermes-gateway.service is not active"

installed_sha="$(git -C "$HERMES_SOURCE" rev-parse HEAD)"
say "Hermes installed SHA: $installed_sha"
[ "$installed_sha" = "$HERMES_EXPECTED_SHA" ] || fail "unsupported Hermes checkout; expected $HERMES_EXPECTED_SHA"

"$HERMES_PYTHON" - "$HERMES_CONFIG" <<'PY'
from pathlib import Path
import sys, yaml
cfg = yaml.safe_load(Path(sys.argv[1]).read_text(encoding="utf-8")) or {}
reasoning = (cfg.get("agent") or {}).get("reasoning_effort")
tg = (cfg.get("platform_toolsets") or {}).get("telegram")
print("agent.reasoning_effort:", repr(reasoning), "type:", type(reasoning).__name__)
print("platform_toolsets.telegram:", repr(tg))
if not isinstance(reasoning, str) or reasoning != "none":
    raise SystemExit("FAIL: reasoning_effort must remain literal string 'none'")
if tg != ["terminal", "file", "web"]:
    raise SystemExit("FAIL: expected fast Telegram profile ['terminal','file','web']")
PY

section "VERIFY PARTIAL STAGE-25 STATE"
"$HERMES_PYTHON" - "$HERMES_RUN" "$BACKUP_DIR/run.py" "$PATCH_BEGIN" "$PATCH_END" <<'PY'
from pathlib import Path
import sys
current = Path(sys.argv[1])
backup = Path(sys.argv[2])
begin, end = sys.argv[3], sys.argv[4]
text = current.read_text(encoding="utf-8")
has_begin = begin in text
has_end = end in text
if has_begin != has_end:
    raise SystemExit("FAIL: partial Stage25 patch markers found in Hermes run.py")
if has_begin:
    if text.count(begin) != 1 or text.count(end) != 1:
        raise SystemExit("FAIL: duplicate Stage25 patch markers found in Hermes run.py")
    print("INFO: Hermes run.py already contains one complete Stage25 patch; repair will validate it idempotently")
else:
    if current.read_bytes() != backup.read_bytes():
        raise SystemExit("FAIL: unpatched Hermes run.py differs from the preserved Stage25 backup; refusing to overwrite an unrelated change")
    print("PASS: Hermes run.py is still exactly the pre-Stage25 backup (initial install did not modify it)")
PY

section "LOAD VERSIONED STAGE-25B FILES"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
for path in "$SKILL_SOURCE" "$EDIT_SOURCE" "$EDIT_TG_SOURCE" "$PATCHER_SOURCE"; do
    out="$work/$(basename "$path")"
    git -C "$AI_REPO" show "${SOURCE_REF}:${path}" > "$out" || fail "cannot load ${path} from ${SOURCE_REF}; run git fetch first"
    [ -s "$out" ] || fail "empty source file: $path"
    say "PASS: loaded $path"
done

git -C "$AI_REPO" show "${SOURCE_REF}:${SKILL_SOURCE}" > "$work/SKILL.md"
git -C "$AI_REPO" show "${SOURCE_REF}:${EDIT_SOURCE}" > "$work/generate-image-edit"
git -C "$AI_REPO" show "${SOURCE_REF}:${EDIT_TG_SOURCE}" > "$work/generate-image-edit-telegram"
git -C "$AI_REPO" show "${SOURCE_REF}:${PATCHER_SOURCE}" > "$work/patch_hermes_foto_media_path_stage25.py"

"$HERMES_PYTHON" -m py_compile "$work/generate-image-edit" "$work/patch_hermes_foto_media_path_stage25.py"
bash -n "$work/generate-image-edit-telegram"
say "PASS: Stage25B source syntax valid"

section "RESOLVE SEMANTIC HERMES PATCH POINT"
"$HERMES_PYTHON" "$work/patch_hermes_foto_media_path_stage25.py" --target "$HERMES_RUN" --check-only
say "PASS: semantic slash-skill patch point is unambiguous"

section "REINSTALL VERSIONED WRAPPERS AND SKILL"
sudo install -m 0755 "$work/generate-image-edit" "$EDIT_DEST"
sudo install -m 0755 "$work/generate-image-edit-telegram" "$EDIT_TG_DEST"
install -m 0644 "$work/SKILL.md" "$SKILL_DEST"
[ -x "$EDIT_DEST" ] || fail "failed to install $EDIT_DEST"
[ -x "$EDIT_TG_DEST" ] || fail "failed to install $EDIT_TG_DEST"
grep -Fq '/usr/local/bin/generate-image-edit-telegram' "$SKILL_DEST" || fail "updated /foto skill lacks image-edit wrapper"
grep -Fq 'HERMES_FOTO_INPUT_IMAGE' "$SKILL_DEST" || fail "updated /foto skill lacks current-turn image path contract"
say "PASS: wrappers and dual-mode /foto skill match versioned branch state"

section "VALIDATE COMFYUI EDIT RUNTIME"
"$EDIT_DEST" --validate-only

section "APPLY SEMANTIC HERMES PATCH"
"$HERMES_PYTHON" "$work/patch_hermes_foto_media_path_stage25.py" --target "$HERMES_RUN"
"$HERMES_PYTHON" -m py_compile "$HERMES_RUN"

"$HERMES_PYTHON" - "$HERMES_RUN" "$PATCH_BEGIN" "$PATCH_END" <<'PY'
from pathlib import Path
import sys
text = Path(sys.argv[1]).read_text(encoding="utf-8")
begin, end = sys.argv[2], sys.argv[3]
required = [
    'if cmd_key == "/foto":',
    'getattr(event, "media_urls", None)',
    '_event_media_is_image(event, _idx)',
    '[HERMES_FOTO_INPUT_IMAGE]',
    'path={_foto_path}',
    'event.media_urls = []',
    'event.media_types = []',
    'event.media_text_inlined = []',
]
missing = [item for item in required if item not in text]
if missing:
    raise SystemExit(f"FAIL: Stage25 bridge contract missing: {missing!r}")
if text.count(begin) != 1 or text.count(end) != 1:
    raise SystemExit("FAIL: Stage25 patch markers are not exactly one complete pair")
print("PASS: patched Hermes source compiles and contains one exact-current-turn /foto bridge")
PY

section "RESTART HERMES"
systemctl --user restart hermes-gateway.service
[ "$(systemctl --user is-active hermes-gateway.service 2>/dev/null || true)" = "active" ] || fail "Hermes failed to restart"
say "PASS: Hermes service active"

section "WAIT FOR TELEGRAM + API"
"$HERMES_PYTHON" - "$HERMES_STATE" <<'PY'
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
    if (state.get("gateway_state") == "running"
            and (platforms.get("telegram") or {}).get("state") == "connected"
            and (platforms.get("api_server") or {}).get("state") == "connected"):
        print("PASS: Hermes gateway running, Telegram connected, API connected")
        break
    time.sleep(1)
else:
    print(json.dumps(last, ensure_ascii=False, indent=2) if last else "<no gateway state>")
    raise SystemExit("FAIL: Hermes did not reconnect within 90 s")
PY

section "POSTCHECK"
"$HERMES_PYTHON" - <<'PY'
import json, urllib.request
with urllib.request.urlopen("http://127.0.0.1:11435/health", timeout=3) as r:
    health = json.load(r)
assert health.get("status") == "ok" and health.get("ollama") == "ok", health
with urllib.request.urlopen("http://127.0.0.1:11435/status", timeout=3) as r:
    status = json.load(r)
print("Gateway active_count:", status.get("active_count"), "queued_count:", status.get("queued_count"))
print("PASS: AI Gateway healthy")
PY

cd "$HERMES_SOURCE"
env HERMES_HOME="$HERMES_HOME" HERMES_PLATFORM="telegram" "$HERMES_PYTHON" - <<'PY'
from agent.skill_commands import scan_skill_commands, build_skill_invocation_message
skills = scan_skill_commands()
if "/foto" not in skills:
    raise SystemExit("FAIL: /foto skill command not registered after restart")
probe = build_skill_invocation_message("/foto", "STAGE25B_EDIT_PROBE")
if not probe or "generate-image-edit-telegram" not in probe or "HERMES_FOTO_INPUT_IMAGE" not in probe:
    raise SystemExit("FAIL: /foto dual-mode skill contract not resolved after restart")
print("PASS: /foto dual-mode skill registered after restart")
PY

section "DONE"
say "PASS: Stage-25B /foto image-edit repair completed"
say "Original rollback backup preserved: $BACKUP_DIR"
say "Text only: /foto <opis> -> new image"
say "Same-message photo caption: /foto <instrukcja> -> edit that exact attached photo"
say "Rollback remains: tools/rollback_hermes_foto_image_edit_stage25.sh"
say "NOTE: reply-to-an-old-photo remains intentionally out of scope."
