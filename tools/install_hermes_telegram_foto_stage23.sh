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
HERMES_EXPECTED_SHA="254158f4530cada634c4ef8f4cff93257c5b4f77"

GENERATOR="/usr/local/bin/generate-image"
TELEGRAM_GENERATOR="/usr/local/bin/generate-image-telegram"
COMFYUI_URL="http://127.0.0.1:8188/system_stats"

SKILL_DIR="${HERMES_HOME}/skills/foto"
SKILL_FILE="${SKILL_DIR}/SKILL.md"
SKILL_MARKER="${HERMES_HOME}/.stage23-foto-skill.sha256"
ROLLBACK_STATE="${HERMES_HOME}/.stage23-foto-rollback-config"
LEGACY_PRE_STAGE_BACKUP="${HERMES_HOME}/config.yaml.pre-stage23-foto"
STAGE23_BACKUP="${HERMES_HOME}/config.yaml.pre-foto-skill-stage23"

say() { printf '%s\n' "$*"; }
section() { printf '\n===== %s =====\n' "$1"; }
fail() { say "FAIL: $*"; exit 1; }

section "STAGE-23 HERMES TELEGRAM /FOTO INSTALL"
say "Adds native Hermes skill command: /foto <prompt>"
say "Uses the already-validated LOCAL pipeline: terminal -> generate-image-telegram -> ComfyUI/FLUX.2 -> Telegram"
say "Telegram toolsets stay at the fast Stage-22 profile: [terminal, file, web]"
say "No Hermes core source files are patched."
say "AI Gateway, Ollama policy and ventilation routing are not modified."

section "PRECHECK"
[ -d "$AI_REPO/.git" ] || fail "AI-server repo missing: $AI_REPO"
[ -d "$HERMES_SOURCE/.git" ] || fail "Hermes source missing: $HERMES_SOURCE"
[ -x "$HERMES_PYTHON" ] || fail "Hermes Python missing: $HERMES_PYTHON"
[ -r "$HERMES_CONFIG" ] || fail "Hermes config missing: $HERMES_CONFIG"
[ -x "$GENERATOR" ] || fail "local image generator missing/not executable: $GENERATOR"
[ -x "$TELEGRAM_GENERATOR" ] || fail "Telegram image wrapper missing/not executable: $TELEGRAM_GENERATOR"
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
telegram = (cfg.get("platform_toolsets") or {}).get("telegram")
print("agent.reasoning_effort:", repr(reasoning), "type:", type(reasoning).__name__)
print("current platform_toolsets.telegram:", repr(telegram))
if not isinstance(reasoning, str) or reasoning != "none":
    raise SystemExit("FAIL: expected literal YAML string agent.reasoning_effort='none'")
PY

"$HERMES_PYTHON" - <<'PY'
import json, urllib.request
with urllib.request.urlopen("http://127.0.0.1:11435/health", timeout=3) as r:
    h = json.load(r)
assert h.get("status") == "ok" and h.get("ollama") == "ok", h
with urllib.request.urlopen("http://127.0.0.1:11435/status", timeout=3) as r:
    s = json.load(r)
print("Gateway active_count:", s.get("active_count"), "queued_count:", s.get("queued_count"), "max_concurrency:", s.get("max_concurrency"))
print("PASS: AI Gateway healthy")
PY

"$HERMES_PYTHON" - "$COMFYUI_URL" <<'PY'
import json, sys, urllib.request
url = sys.argv[1]
with urllib.request.urlopen(url, timeout=5) as r:
    data = json.load(r)
print("PASS: ComfyUI API reachable")
print("ComfyUI system_stats keys:", sorted(data.keys()))
PY

section "LOAD VERSIONED /FOTO SKILL"
tmp_skill="$(mktemp)"
trap 'rm -f "${tmp_skill:-}"' EXIT
if ! git -C "$AI_REPO" show "${SOURCE_REF}:${SKILL_REPO_PATH}" > "$tmp_skill"; then
    fail "cannot read ${SKILL_REPO_PATH} from ${SOURCE_REF}; run git fetch first"
fi
[ -s "$tmp_skill" ] || fail "versioned foto skill is empty"
source_skill_sha="$(sha256sum "$tmp_skill" | awk '{print $1}')"
say "source ref:       $SOURCE_REF"
say "source skill SHA: $source_skill_sha"

if [ -e "$SKILL_FILE" ]; then
    current_skill_sha="$(sha256sum "$SKILL_FILE" | awk '{print $1}')"
    if [ -r "$SKILL_MARKER" ] && [ "$(cat "$SKILL_MARKER")" = "$current_skill_sha" ]; then
        say "INFO: earlier Stage-23 managed /foto skill found; safe idempotent replacement"
    elif [ "$current_skill_sha" = "$source_skill_sha" ]; then
        say "INFO: identical /foto skill already present; adopting it as Stage-23 managed"
    else
        fail "${SKILL_FILE} already exists and is not Stage-23 managed; refusing to overwrite"
    fi
fi

section "SELECT REVERSIBLE CONFIG BACKUP"
if [ -r "$ROLLBACK_STATE" ]; then
    rollback_config="$(cat "$ROLLBACK_STATE")"
    [ -r "$rollback_config" ] || fail "recorded rollback config is missing: $rollback_config"
    say "INFO: preserving recorded rollback source: $rollback_config"
elif [ -r "$LEGACY_PRE_STAGE_BACKUP" ]; then
    rollback_config="$LEGACY_PRE_STAGE_BACKUP"
    printf '%s\n' "$rollback_config" > "$ROLLBACK_STATE"
    chmod 600 "$ROLLBACK_STATE"
    say "PASS: adopted existing pre-foto backup: $rollback_config"
else
    rollback_config="$STAGE23_BACKUP"
    if [ ! -e "$rollback_config" ]; then
        cp --preserve=mode,timestamps "$HERMES_CONFIG" "$rollback_config"
    fi
    printf '%s\n' "$rollback_config" > "$ROLLBACK_STATE"
    chmod 600 "$ROLLBACK_STATE"
    say "PASS: created Stage-23 config backup: $rollback_config"
fi

section "RESTORE FAST TELEGRAM PROFILE"
"$HERMES_PYTHON" - "$HERMES_CONFIG" <<'PY'
from pathlib import Path
import os, sys, tempfile, yaml
path = Path(sys.argv[1])
cfg = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
agent = cfg.setdefault("agent", {})
if not isinstance(agent, dict) or agent.get("reasoning_effort") != "none":
    raise SystemExit("FAIL: refusing update because reasoning_effort is not literal 'none'")
platform = cfg.setdefault("platform_toolsets", {})
if not isinstance(platform, dict):
    raise SystemExit("FAIL: config.platform_toolsets is not a mapping")
# Deliberately do NOT expose Hermes image_generate. /foto uses the validated
# local ComfyUI wrapper through the already-enabled terminal tool.
platform["telegram"] = ["terminal", "file", "web"]
fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".stage23foto.", dir=str(path.parent), text=True)
try:
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        yaml.safe_dump(cfg, f, allow_unicode=True, sort_keys=False)
        f.flush(); os.fsync(f.fileno())
    os.chmod(tmp_name, path.stat().st_mode)
    os.replace(tmp_name, path)
finally:
    try: os.unlink(tmp_name)
    except FileNotFoundError: pass
print("PASS: platform_toolsets.telegram = ['terminal', 'file', 'web']")
PY

section "INSTALL /FOTO SKILL"
mkdir -p "$SKILL_DIR"
tmp_dest="$(mktemp "${SKILL_DIR}/.SKILL.md.stage23.XXXXXX")"
cp "$tmp_skill" "$tmp_dest"
chmod 0644 "$tmp_dest"
mv -f "$tmp_dest" "$SKILL_FILE"
printf '%s\n' "$source_skill_sha" > "$SKILL_MARKER"
chmod 600 "$SKILL_MARKER"
say "PASS: installed $SKILL_FILE"

section "VALIDATE INSTALLED HERMES RESOLUTION"
cd "$HERMES_SOURCE"
env HERMES_HOME="$HERMES_HOME" HERMES_PLATFORM="telegram" "$HERMES_PYTHON" - "$HERMES_CONFIG" <<'PY'
from pathlib import Path
import sys, yaml
cfg = yaml.safe_load(Path(sys.argv[1]).read_text(encoding="utf-8")) or {}
telegram = (cfg.get("platform_toolsets") or {}).get("telegram")
reasoning = (cfg.get("agent") or {}).get("reasoning_effort")
print("raw platform_toolsets.telegram:", repr(telegram))
print("agent.reasoning_effort:", repr(reasoning), "type:", type(reasoning).__name__)
if telegram != ["terminal", "file", "web"]:
    raise SystemExit(f"FAIL: unexpected Telegram toolsets: {telegram!r}")
if not isinstance(reasoning, str) or reasoning != "none":
    raise SystemExit("FAIL: reasoning_effort changed or is not a string")

from hermes_cli.tools_config import _get_platform_tools
resolved = set(_get_platform_tools(cfg, "telegram"))
print("Hermes resolved Telegram toolsets:", sorted(resolved))
if not {"terminal", "file", "web"}.issubset(resolved):
    raise SystemExit(f"FAIL: Stage-22 Telegram toolsets not resolved: {sorted(resolved)!r}")

import model_tools
model_tools._clear_tool_defs_cache()
defs = model_tools.get_tool_definitions(enabled_toolsets=sorted(resolved), quiet_mode=True, skip_tool_search_assembly=True)
visible = {str((tool.get("function") or {}).get("name") or "") for tool in defs if (tool.get("function") or {}).get("name")}
print("raw model-facing Telegram tools:", sorted(visible))
base_required = {"terminal", "process_manage", "read_file", "write_file", "patch", "search_files", "web_search", "web_extract"}
missing = base_required - visible
if missing:
    raise SystemExit(f"FAIL: Stage-22 base tools disappeared: {sorted(missing)!r}")
if "image_generate" in visible:
    raise SystemExit("FAIL: image_generate unexpectedly visible; /foto must remain on local wrapper path")
print("PASS: fast Stage-22 model-facing tool surface preserved; image_generate absent")

from agent.skill_commands import scan_skill_commands, build_skill_invocation_message
skills = scan_skill_commands()
if "/foto" not in skills:
    raise SystemExit("FAIL: installed Hermes did not register /foto as a skill command")
print("/foto skill registration:", skills["/foto"].get("name"), "-", skills["/foto"].get("description"))
probe = "STAGE23_FOTO_PROMPT_PROBE"
expanded = build_skill_invocation_message("/foto", probe)
if not expanded:
    raise SystemExit("FAIL: build_skill_invocation_message('/foto') returned no message")
if probe not in expanded:
    raise SystemExit("FAIL: /foto argument was not forwarded into the skill invocation")
if "/usr/local/bin/generate-image-telegram" not in expanded:
    raise SystemExit("FAIL: /foto skill does not target the validated local Telegram image wrapper")
if "requires_toolsets: [image_gen]" in expanded:
    raise SystemExit("FAIL: /foto skill still requires the Hermes image_gen toolset")
print("PASS: /foto registered and routes its argument to local generate-image-telegram")
PY

section "RESTART HERMES"
systemctl --user restart hermes-gateway.service
[ "$(systemctl --user is-active hermes-gateway.service 2>/dev/null || true)" = "active" ] || fail "hermes-gateway.service did not become active"
say "PASS: Hermes service active"

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
    raise SystemExit("FAIL: Hermes did not fully reconnect within 90 s")
PY

section "POSTCHECK"
"$HERMES_PYTHON" - <<'PY'
import json, urllib.request
with urllib.request.urlopen("http://127.0.0.1:11435/health", timeout=3) as r: h = json.load(r)
assert h.get("status") == "ok" and h.get("ollama") == "ok", h
print("PASS: AI Gateway healthy")
PY

section "DONE"
say "PASS: Stage-23 native Telegram /foto installed"
say "Route: /foto -> Hermes skill -> terminal -> generate-image-telegram -> local ComfyUI/FLUX -> Telegram PNG"
say "Normal Telegram chat remains on [terminal, file, web] with no image_generate schema overhead."
say "Use: /foto <opis obrazu>"
say "Rollback script: tools/rollback_hermes_telegram_foto_stage23.sh"
say "Rollback config source: $rollback_config"
