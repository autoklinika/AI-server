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
SKILL_DEST="${HERMES_HOME}/skills/foto/SKILL.md"
EDIT_DEST="/usr/local/bin/generate-image-edit"
EDIT_TG_DEST="/usr/local/bin/generate-image-edit-telegram"

BACKUP_DIR="${HERMES_HOME}/stage25-foto-edit-backup"
PATCH_BEGIN="# AI_SERVER_STAGE25_FOTO_MEDIA_PATH_BEGIN"
PATCH_END="# AI_SERVER_STAGE25_FOTO_MEDIA_PATH_END"

say() { printf '%s\n' "$*"; }
section() { printf '\n===== %s =====\n' "$1"; }
fail() { say "FAIL: $*"; exit 1; }

section "STAGE-25 /FOTO IMAGE EDIT INSTALL"
say "Adds image-edit mode for a photo attached to the SAME /foto Telegram message."
say "Text-only /foto keeps the existing text-to-image path."
say "Uses exact current-turn event.media_urls path; no newest-file guessing."
say "Telegram profile stays [terminal, file, web]."
say "Hermes patch is pinned to exact installed SHA and fully reversible."

section "PRECHECK"
[ -d "$AI_REPO/.git" ] || fail "AI-server repo missing: $AI_REPO"
[ -d "$HERMES_SOURCE/.git" ] || fail "Hermes source missing: $HERMES_SOURCE"
[ -x "$HERMES_PYTHON" ] || fail "Hermes Python missing: $HERMES_PYTHON"
[ -r "$HERMES_RUN" ] || fail "Hermes gateway/run.py missing"
[ -r "$HERMES_CONFIG" ] || fail "Hermes config missing"
[ -r "$SKILL_DEST" ] || fail "working /foto skill missing; install Stage23 first"
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
print("agent.reasoning_effort:", repr(reasoning))
print("platform_toolsets.telegram:", repr(tg))
if reasoning != "none" or not isinstance(reasoning, str):
    raise SystemExit("FAIL: reasoning_effort must remain literal string 'none'")
if tg != ["terminal", "file", "web"]:
    raise SystemExit("FAIL: expected fast Telegram profile ['terminal','file','web']")
PY

section "LOAD VERSIONED FILES"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
for path in "$SKILL_SOURCE" "$EDIT_SOURCE" "$EDIT_TG_SOURCE"; do
    out="$work/$(basename "$path")"
    git -C "$AI_REPO" show "${SOURCE_REF}:${path}" > "$out" || fail "cannot load ${path} from ${SOURCE_REF}"
    [ -s "$out" ] || fail "empty source file: $path"
    say "PASS: loaded $path"
done

# basename collision is intentional only for unique names here; SKILL.md needs explicit copy.
git -C "$AI_REPO" show "${SOURCE_REF}:${SKILL_SOURCE}" > "$work/SKILL.md"
git -C "$AI_REPO" show "${SOURCE_REF}:${EDIT_SOURCE}" > "$work/generate-image-edit"
git -C "$AI_REPO" show "${SOURCE_REF}:${EDIT_TG_SOURCE}" > "$work/generate-image-edit-telegram"

"$HERMES_PYTHON" -m py_compile "$work/generate-image-edit"
bash -n "$work/generate-image-edit-telegram"
say "PASS: versioned generator syntax valid"

section "CREATE REVERSIBLE BACKUP"
if [ ! -d "$BACKUP_DIR" ]; then
    mkdir -p "$BACKUP_DIR"
    chmod 700 "$BACKUP_DIR"
    cp --preserve=mode,timestamps "$HERMES_RUN" "$BACKUP_DIR/run.py"
    cp --preserve=mode,timestamps "$SKILL_DEST" "$BACKUP_DIR/SKILL.md"
    if [ -e "$EDIT_DEST" ]; then
        sudo cp --preserve=mode,timestamps "$EDIT_DEST" "$BACKUP_DIR/generate-image-edit"
    else
        : > "$BACKUP_DIR/generate-image-edit.ABSENT"
    fi
    if [ -e "$EDIT_TG_DEST" ]; then
        sudo cp --preserve=mode,timestamps "$EDIT_TG_DEST" "$BACKUP_DIR/generate-image-edit-telegram"
    else
        : > "$BACKUP_DIR/generate-image-edit-telegram.ABSENT"
    fi
    say "PASS: backup created: $BACKUP_DIR"
else
    [ -r "$BACKUP_DIR/run.py" ] || fail "Stage25 backup exists but run.py backup missing"
    [ -r "$BACKUP_DIR/SKILL.md" ] || fail "Stage25 backup exists but SKILL.md backup missing"
    say "INFO: preserving existing Stage25 backup unchanged"
fi

section "INSTALL LOCAL IMAGE EDIT WRAPPERS"
sudo install -m 0755 "$work/generate-image-edit" "$EDIT_DEST"
sudo install -m 0755 "$work/generate-image-edit-telegram" "$EDIT_TG_DEST"
[ -x "$EDIT_DEST" ] || fail "failed to install $EDIT_DEST"
[ -x "$EDIT_TG_DEST" ] || fail "failed to install $EDIT_TG_DEST"
say "PASS: installed image-edit wrappers"

section "VALIDATE COMFYUI EDIT RUNTIME"
"$EDIT_DEST" --validate-only

section "INSTALL UPDATED /FOTO SKILL"
install -m 0644 "$work/SKILL.md" "$SKILL_DEST"
grep -Fq '/usr/local/bin/generate-image-edit-telegram' "$SKILL_DEST" || fail "updated skill lacks image-edit wrapper"
grep -Fq 'HERMES_FOTO_INPUT_IMAGE' "$SKILL_DEST" || fail "updated skill lacks current-turn path contract"
say "PASS: installed dual-mode /foto skill"

section "PATCH PINNED HERMES SLASH-SKILL DISPATCH"
"$HERMES_PYTHON" - "$HERMES_RUN" "$PATCH_BEGIN" "$PATCH_END" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
begin, end = sys.argv[2], sys.argv[3]
text = path.read_text(encoding="utf-8")

if begin in text:
    if end not in text:
        raise SystemExit("FAIL: partial Stage25 Hermes patch marker found")
    print("INFO: Stage25 Hermes patch already present; leaving unchanged")
    raise SystemExit(0)

needle = "                    user_instruction = event.get_command_args().strip()\n"
if text.count(needle) != 1:
    raise SystemExit(f"FAIL: expected exactly one slash-skill user_instruction anchor, found {text.count(needle)}")

patch = '''                    user_instruction = event.get_command_args().strip()\n                    # AI_SERVER_STAGE25_FOTO_MEDIA_PATH_BEGIN\n                    # /foto image editing needs the exact cached path from THIS inbound\n                    # event.  Inject it into the skill instruction before normal media\n                    # enrichment, then consume the image attachment so Qwen does not\n                    # waste a vision pass merely to route a deterministic local edit.\n                    if cmd_key == "/foto":\n                        _foto_image_paths = [\n                            str(_path)\n                            for _idx, _path in enumerate(getattr(event, "media_urls", None) or [])\n                            if _event_media_is_image(event, _idx)\n                        ]\n                        if _foto_image_paths:\n                            _foto_path = _foto_image_paths[0]\n                            user_instruction = (\n                                f"{user_instruction}\\n\\n"\n                                "[HERMES_FOTO_INPUT_IMAGE]\\n"\n                                f"path={_foto_path}\\n"\n                                "[/HERMES_FOTO_INPUT_IMAGE]"\n                            )\n                            event.media_urls = []\n                            event.media_types = []\n                            event.media_text_inlined = []\n                    # AI_SERVER_STAGE25_FOTO_MEDIA_PATH_END\n'''

text = text.replace(needle, patch, 1)
path.write_text(text, encoding="utf-8")
print("PASS: injected exact-current-turn /foto image path bridge")
PY

"$HERMES_PYTHON" -m py_compile "$HERMES_RUN"
grep -Fq "$PATCH_BEGIN" "$HERMES_RUN" || fail "Hermes patch begin marker missing"
grep -Fq "$PATCH_END" "$HERMES_RUN" || fail "Hermes patch end marker missing"
say "PASS: patched Hermes source compiles"

section "STATIC PATH-BRIDGE CONTRACT TEST"
"$HERMES_PYTHON" - "$HERMES_RUN" <<'PY'
from pathlib import Path
import sys
text = Path(sys.argv[1]).read_text(encoding="utf-8")
required = [
    'if cmd_key == "/foto":',
    'getattr(event, "media_urls", None)',
    '_event_media_is_image(event, _idx)',
    '[HERMES_FOTO_INPUT_IMAGE]',
    'path={_foto_path}',
    'event.media_urls = []',
]
missing = [item for item in required if item not in text]
if missing:
    raise SystemExit(f"FAIL: patched bridge contract missing: {missing!r}")
print("PASS: /foto slash-skill receives exact current-turn image path and consumes vision attachment")
PY

section "RESTART HERMES"
systemctl --user restart hermes-gateway.service
[ "$(systemctl --user is-active hermes-gateway.service 2>/dev/null || true)" = "active" ] || fail "Hermes failed to restart"
say "PASS: Hermes service active"

section "WAIT FOR TELEGRAM + API"
"$HERMES_PYTHON" - "$HERMES_STATE" <<'PY'
from pathlib import Path
import json, sys, time
path = Path(sys.argv[1]); deadline = time.monotonic() + 90; last = None
while time.monotonic() < deadline:
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        time.sleep(1); continue
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

cd "$HERMES_SOURCE"
env HERMES_HOME="$HERMES_HOME" HERMES_PLATFORM="telegram" "$HERMES_PYTHON" - <<'PY'
from agent.skill_commands import scan_skill_commands, build_skill_invocation_message
skills = scan_skill_commands()
assert "/foto" in skills, skills.keys()
probe = build_skill_invocation_message("/foto", "STAGE25_EDIT_PROBE")
assert probe and "generate-image-edit-telegram" in probe
assert "HERMES_FOTO_INPUT_IMAGE" in probe
print("PASS: /foto registered with image-edit contract")
PY

section "DONE"
say "PASS: Stage-25 /foto image-edit support installed"
say "Text only: /foto <opis> -> new image"
say "Photo caption: attach photo + /foto <instrukcja> -> edit that exact photo"
say "Rollback: tools/rollback_hermes_foto_image_edit_stage25.sh"
say "NOTE: reply-to-an-old-photo is NOT enabled by this stage; Stage25 handles an image attached to the same message."
