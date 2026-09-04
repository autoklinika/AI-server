#!/usr/bin/env bash
set -euo pipefail

AI_REPO="${AI_SERVER_REPO:-$HOME/AI-server}"
SOURCE_REF="${AI_SERVER_SOURCE_REF:-origin/feat/hermes-telegram-foto}"
SKILL_REPO_PATH="deploy/hermes/skills/foto/SKILL.md"

HERMES_HOME="/srv/ai-data/hermes"
HERMES_SOURCE="${HERMES_HOME}/hermes-agent"
HERMES_PYTHON="${HERMES_SOURCE}/venv/bin/python"
HERMES_CONFIG="${HERMES_HOME}/config.yaml"
HERMES_STATE="${HERMES_HOME}/gateway_state.json"
SKILL_DIR="${HERMES_HOME}/skills/foto"
SKILL_FILE="${SKILL_DIR}/SKILL.md"
SKILL_MARKER="${HERMES_HOME}/.stage23-foto-skill.sha256"
BAD_PATH="/srv/ai-data/hermes/bin/generate-image-telegram"
GOOD_PATH="/usr/local/bin/generate-image-telegram"
BACKUP="${SKILL_DIR}/SKILL.md.bad-stage23c-backup"

say() { printf '%s\n' "$*"; }
section() { printf '\n===== %s =====\n' "$1"; }
fail() { say "FAIL: $*"; exit 1; }

section "STAGE-23D REPAIR /FOTO WRAPPER PATH"
say "Repairs only the known Stage-23C bad path."
say "Bad:  $BAD_PATH"
say "Good: $GOOD_PATH"

section "PRECHECK"
[ -d "$AI_REPO/.git" ] || fail "AI-server repo missing: $AI_REPO"
[ -d "$HERMES_SOURCE/.git" ] || fail "Hermes source missing: $HERMES_SOURCE"
[ -x "$HERMES_PYTHON" ] || fail "Hermes Python missing: $HERMES_PYTHON"
[ -r "$HERMES_CONFIG" ] || fail "Hermes config missing: $HERMES_CONFIG"
[ -r "$SKILL_FILE" ] || fail "/foto skill missing: $SKILL_FILE"
[ -x "$GOOD_PATH" ] || fail "validated wrapper missing/not executable: $GOOD_PATH"
[ "$(systemctl --user is-active hermes-gateway.service 2>/dev/null || true)" = "active" ] || fail "hermes-gateway.service is not active"
[ "$(systemctl is-active comfyui.service 2>/dev/null || true)" = "active" ] || fail "comfyui.service is not active"

"$HERMES_PYTHON" - "$HERMES_CONFIG" <<'PY'
from pathlib import Path
import sys, yaml
cfg = yaml.safe_load(Path(sys.argv[1]).read_text(encoding="utf-8")) or {}
reasoning = (cfg.get("agent") or {}).get("reasoning_effort")
telegram = (cfg.get("platform_toolsets") or {}).get("telegram")
print("agent.reasoning_effort:", repr(reasoning))
print("platform_toolsets.telegram:", repr(telegram))
if reasoning != "none":
    raise SystemExit("FAIL: expected reasoning_effort='none'")
if telegram != ["terminal", "file", "web"]:
    raise SystemExit(f"FAIL: expected fast Telegram profile [terminal,file,web], got {telegram!r}")
PY

section "VERIFY KNOWN BAD LOCAL SKILL"
if grep -Fq "$GOOD_PATH" "$SKILL_FILE" && ! grep -Fq "$BAD_PATH" "$SKILL_FILE"; then
    say "INFO: local /foto skill already has the correct wrapper path"
elif grep -Fq "$BAD_PATH" "$SKILL_FILE"; then
    grep -Fq "name: foto" "$SKILL_FILE" || fail "bad path found but file is not clearly the foto skill; refusing overwrite"
    if [ ! -e "$BACKUP" ]; then
        cp --preserve=mode,timestamps "$SKILL_FILE" "$BACKUP"
        say "PASS: backed up bad Stage-23C skill: $BACKUP"
    else
        say "INFO: backup already exists; preserving it: $BACKUP"
    fi
else
    fail "local /foto skill does not contain the known bad path or expected good path; refusing overwrite"
fi

section "LOAD VERSIONED GOOD SKILL"
tmp_skill="$(mktemp)"
trap 'rm -f "${tmp_skill:-}"' EXIT
if ! git -C "$AI_REPO" show "${SOURCE_REF}:${SKILL_REPO_PATH}" > "$tmp_skill"; then
    fail "cannot read ${SKILL_REPO_PATH} from ${SOURCE_REF}; run git fetch first"
fi
[ -s "$tmp_skill" ] || fail "versioned foto skill is empty"
grep -Fq "$GOOD_PATH" "$tmp_skill" || fail "versioned skill does not contain expected good wrapper path"
if grep -Fq "$BAD_PATH" "$tmp_skill"; then
    fail "versioned skill still contains known bad wrapper path"
fi
source_sha="$(sha256sum "$tmp_skill" | awk '{print $1}')"
say "versioned skill SHA: $source_sha"

section "ATOMIC REPAIR"
mkdir -p "$SKILL_DIR"
tmp_dest="$(mktemp "${SKILL_DIR}/.SKILL.md.stage23d.XXXXXX")"
cp "$tmp_skill" "$tmp_dest"
chmod 0644 "$tmp_dest"
mv -f "$tmp_dest" "$SKILL_FILE"
printf '%s\n' "$source_sha" > "$SKILL_MARKER"
chmod 600 "$SKILL_MARKER"
say "PASS: restored versioned /foto skill"

section "VALIDATE HERMES SKILL REGISTRATION"
cd "$HERMES_SOURCE"
env HERMES_HOME="$HERMES_HOME" HERMES_PLATFORM="telegram" "$HERMES_PYTHON" - <<'PY'
from agent.skill_commands import scan_skill_commands, build_skill_invocation_message
skills = scan_skill_commands()
if "/foto" not in skills:
    raise SystemExit("FAIL: /foto is not registered")
probe = "STAGE23D_PROMPT_PROBE"
expanded = build_skill_invocation_message("/foto", probe)
if not expanded or probe not in expanded:
    raise SystemExit("FAIL: /foto does not forward its prompt")
if "/usr/local/bin/generate-image-telegram" not in expanded:
    raise SystemExit("FAIL: /foto expansion does not contain correct wrapper path")
if "/srv/ai-data/hermes/bin/generate-image-telegram" in expanded:
    raise SystemExit("FAIL: /foto expansion still contains bad wrapper path")
print("PASS: /foto registered, prompt forwarded, correct wrapper path resolved")
PY

section "RESTART HERMES"
systemctl --user restart hermes-gateway.service
[ "$(systemctl --user is-active hermes-gateway.service 2>/dev/null || true)" = "active" ] || fail "Hermes did not become active"

section "WAIT FOR TELEGRAM + API"
"$HERMES_PYTHON" - "$HERMES_STATE" <<'PY'
from pathlib import Path
import json, sys, time
path = Path(sys.argv[1]); deadline = time.monotonic() + 90; last = None
while time.monotonic() < deadline:
    try: state = json.loads(path.read_text(encoding="utf-8"))
    except Exception: time.sleep(1); continue
    last = state; platforms = state.get("platforms") or {}
    if state.get("gateway_state") == "running" and (platforms.get("telegram") or {}).get("state") == "connected" and (platforms.get("api_server") or {}).get("state") == "connected":
        print("PASS: Hermes gateway running, Telegram connected, API connected"); break
    time.sleep(1)
else:
    print(json.dumps(last, ensure_ascii=False, indent=2) if last else "<no readable gateway_state>")
    raise SystemExit("FAIL: Hermes did not reconnect within 90s")
PY

section "DONE"
say "PASS: Stage-23D repaired /foto wrapper path"
say "Test now: /foto czarny kot astronauta na Księżycu, cinematic, realistycznie"
