#!/usr/bin/env bash
set -euo pipefail

HERMES_HOME="/srv/ai-data/hermes"
HERMES_SOURCE="${HERMES_HOME}/hermes-agent"
HERMES_PYTHON="${HERMES_SOURCE}/venv/bin/python"
HERMES_CONFIG="${HERMES_HOME}/config.yaml"
HERMES_STATE="${HERMES_HOME}/gateway_state.json"
HERMES_EXPECTED_SHA="79445a496c86a19332ad786494b8384d2167e2d0"
HERMES_RUN="${HERMES_SOURCE}/gateway/run_inbound.py"

DISPATCH_DST="/usr/local/bin/hermes-foto-dispatch"
LIBEXEC="/usr/local/libexec/ai-server"
COMPILER_DST="${LIBEXEC}/hermes_foto_prompt_compiler.py"
BACKUP_DIR="${HERMES_HOME}/stage28-foto-modern-backup"

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
DISPATCH_SRC="${SCRIPT_DIR}/local_image/hermes_foto_dispatch.py"
COMPILER_SRC="${SCRIPT_DIR}/local_image/hermes_foto_prompt_compiler.py"
PATCHER="${SCRIPT_DIR}/patch_hermes_foto_quick_media_stage28.py"

SUCCESS=0
MUTATED=0

say(){ printf '%s\n' "$*"; }
section(){ printf '\n===== %s =====\n' "$1"; }
fail(){ say "FAIL: $*" >&2; exit 1; }

restore_optional(){
    local dst="$1" name="$2"
    if [ -r "$BACKUP_DIR/${name}.ABSENT" ]; then
        sudo rm -f "$dst"
    elif [ -r "$BACKUP_DIR/$name" ]; then
        sudo cp -a "$BACKUP_DIR/$name" "$dst"
    fi
}

restore_from_backup(){
    [ -d "$BACKUP_DIR" ] || return 0
    if [ -r "$BACKUP_DIR/run_inbound.py" ]; then
        cp -a "$BACKUP_DIR/run_inbound.py" "$HERMES_RUN"
    fi
    if [ -r "$BACKUP_DIR/config.yaml" ]; then
        cp -a "$BACKUP_DIR/config.yaml" "$HERMES_CONFIG"
    fi
    restore_optional "$DISPATCH_DST" "hermes-foto-dispatch"
    restore_optional "$COMPILER_DST" "hermes_foto_prompt_compiler.py"
    systemctl --user restart hermes-gateway.service >/dev/null 2>&1 || true
}

cleanup(){
    rc=$?
    trap - EXIT INT TERM
    if [ "$SUCCESS" -ne 1 ] && [ "$MUTATED" -eq 1 ]; then
        echo
        echo "===== AUTOMATIC ROLLBACK ====="
        restore_from_backup
    fi
    exit "$rc"
}
trap cleanup EXIT INT TERM

wait_hermes(){
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
        raise SystemExit(0)
    time.sleep(1)
print(json.dumps(last, ensure_ascii=False, indent=2) if last else "<no gateway state>")
raise SystemExit(1)
PY
}

backup_optional(){
    local src="$1" name="$2"
    if [ -e "$BACKUP_DIR/$name" ] || [ -e "$BACKUP_DIR/${name}.ABSENT" ]; then
        return 0
    fi
    if sudo test -e "$src"; then
        sudo cp -a "$src" "$BACKUP_DIR/$name"
    else
        : > "$BACKUP_DIR/${name}.ABSENT"
    fi
}

section "STAGE 28 - MODERN HERMES /FOTO"
say "Route: Telegram /foto -> exact quick_command -> local Qwen prompt compiler -> FLUX -> exact invoking chat."
say "Text-only /foto generates a new image; an image attached to the same message selects edit mode."
say "Qwen converts Polish/free-form requests into explicit English FLUX prompts before rendering."
say "Edit-like text without an attached image is rejected before FLUX instead of producing garbage output."
say "Stage27 /wideo, Ollama/ComfyUI configuration and ventilation are not modified."

section "PRECHECK"
[ -d "$HERMES_SOURCE/.git" ] || fail "Hermes source missing"
[ -x "$HERMES_PYTHON" ] || fail "Hermes Python missing"
[ -r "$HERMES_CONFIG" ] || fail "Hermes config missing"
[ -r "$HERMES_RUN" ] || fail "modern gateway/run_inbound.py missing"
[ -r "$DISPATCH_SRC" ] || fail "Stage28 dispatcher source missing"
[ -r "$COMPILER_SRC" ] || fail "Stage28 prompt compiler source missing"
[ -r "$PATCHER" ] || fail "Stage28 patcher source missing"
[ -x /usr/local/bin/generate-image ] || fail "working text-to-image generator missing: /usr/local/bin/generate-image"
[ -x /usr/local/bin/generate-image-edit ] || fail "working image-edit generator missing: /usr/local/bin/generate-image-edit"
[ "$(systemctl is-active comfyui.service 2>/dev/null || true)" = "active" ] || fail "comfyui.service is not active"
[ "$(systemctl is-active ai-gateway.service 2>/dev/null || true)" = "active" ] || fail "ai-gateway.service is not active"
[ "$(systemctl --user is-active hermes-gateway.service 2>/dev/null || true)" = "active" ] || fail "hermes-gateway.service is not active"

installed_sha="$(git -C "$HERMES_SOURCE" rev-parse HEAD)"
say "Hermes installed SHA: $installed_sha"
[ "$installed_sha" = "$HERMES_EXPECTED_SHA" ] || fail "unsupported Hermes checkout; expected $HERMES_EXPECTED_SHA"

"$HERMES_PYTHON" -m py_compile "$DISPATCH_SRC" "$COMPILER_SRC" "$PATCHER"
patch_state="$("$HERMES_PYTHON" "$PATCHER" "$HERMES_RUN" --check)" || fail "Stage28 Hermes patch target unsupported: $patch_state"
say "Hermes /foto media bridge: $patch_state"

grep -Fq 'STAGE26_WIDEO_QUICK_ARGS' "$HERMES_RUN" || fail "Stage26 quick-command argument bridge missing"
grep -Fq 'STAGE26_WIDEO_ROUTE_ENV' "$HERMES_RUN" || fail "Stage26 exact-chat route bridge missing"

"$HERMES_PYTHON" - "$HERMES_CONFIG" <<'PY'
from pathlib import Path
import sys, yaml
cfg = yaml.safe_load(Path(sys.argv[1]).read_text(encoding="utf-8")) or {}
qc = cfg.get("quick_commands") or {}
wideo = qc.get("wideo")
print("current quick_commands.wideo:", wideo)
print("current quick_commands.foto:", qc.get("foto"))
if not isinstance(wideo, dict) or wideo.get("type") != "exec":
    raise SystemExit("FAIL: Stage26/27 /wideo quick command missing; refusing cumulative Stage28 cutover")
PY

section "BACKUP PRE-STAGE-28 STATE"
mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"
if [ ! -e "$BACKUP_DIR/run_inbound.py" ]; then
    cp --preserve=mode,timestamps "$HERMES_RUN" "$BACKUP_DIR/run_inbound.py"
    cp --preserve=mode,timestamps "$HERMES_CONFIG" "$BACKUP_DIR/config.yaml"
    say "PASS: Stage28 reversible core backup created"
else
    [ -r "$BACKUP_DIR/config.yaml" ] || fail "Stage28 backup incomplete: config.yaml missing"
    say "INFO: preserving existing pre-Stage28 core backup"
fi
backup_optional "$DISPATCH_DST" "hermes-foto-dispatch"
backup_optional "$COMPILER_DST" "hermes_foto_prompt_compiler.py"

section "PATCH MODERN HERMES /FOTO MEDIA BRIDGE"
MUTATED=1
"$HERMES_PYTHON" "$PATCHER" "$HERMES_RUN"
"$HERMES_PYTHON" -m py_compile "$HERMES_RUN"
grep -Fq 'STAGE28_FOTO_MEDIA_ENV' "$HERMES_RUN" || fail "Stage28 media bridge marker missing"
say "PASS: exact current-turn image path is bridged only for /foto"

section "INSTALL QWEN PROMPT COMPILER + /FOTO DISPATCHER"
sudo install -d -m 0755 "$LIBEXEC"
sudo install -m 0644 "$COMPILER_SRC" "$COMPILER_DST"
sudo install -m 0755 "$DISPATCH_SRC" "$DISPATCH_DST"
# Validate root-owned production files without trying to create __pycache__ in /usr/local.
"$HERMES_PYTHON" - "$DISPATCH_DST" "$COMPILER_DST" <<'PY'
from pathlib import Path
import sys
for raw in sys.argv[1:]:
    path = Path(raw)
    compile(path.read_text(encoding="utf-8"), str(path), "exec")
    print("PASS: syntax valid:", path)
PY
"$DISPATCH_DST" --preflight
say "PASS: local image generators + Qwen compiler + Hermes delivery CLI available"

section "CONFIGURE /FOTO QUICK COMMAND"
"$HERMES_PYTHON" - "$HERMES_CONFIG" <<'PY'
from pathlib import Path
import os, sys, tempfile, yaml
path = Path(sys.argv[1])
cfg = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
qc = cfg.setdefault("quick_commands", {})
if not isinstance(qc, dict):
    raise SystemExit("FAIL: quick_commands is not a mapping")
qc["foto"] = {"type": "exec", "command": "/usr/local/bin/hermes-foto-dispatch"}
fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".stage28.", dir=str(path.parent), text=True)
try:
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        yaml.safe_dump(cfg, handle, allow_unicode=True, sort_keys=False)
        handle.flush(); os.fsync(handle.fileno())
    os.chmod(tmp_name, path.stat().st_mode)
    os.replace(tmp_name, path)
finally:
    try: os.unlink(tmp_name)
    except FileNotFoundError: pass
print("PASS: quick_commands.foto -> /usr/local/bin/hermes-foto-dispatch")
PY

section "RESTART HERMES ONLY"
systemctl --user restart hermes-gateway.service
wait_hermes || fail "Hermes failed to reconnect after Stage28 cutover"

section "POSTCHECK"
"$HERMES_PYTHON" - "$HERMES_CONFIG" <<'PY'
from pathlib import Path
import sys, yaml
cfg = yaml.safe_load(Path(sys.argv[1]).read_text(encoding="utf-8")) or {}
qc = cfg.get("quick_commands") or {}
foto = qc.get("foto")
wideo = qc.get("wideo")
print("quick_commands.foto:", foto)
print("quick_commands.wideo:", wideo)
assert foto == {"type": "exec", "command": "/usr/local/bin/hermes-foto-dispatch"}, foto
assert isinstance(wideo, dict) and wideo.get("type") == "exec", wideo
print("PASS: /foto deterministic quick command active; /wideo preserved")
PY

SUCCESS=1
MUTATED=0

section "DONE"
say "PASS: Stage28 modern Hermes /foto installed with Qwen prompt compiler"
say "Generate: /foto <opis> -> Qwen English FLUX prompt -> local FLUX -> exact invoking chat"
say "Edit: attach image + caption '/foto <instrukcja>' -> Qwen edit prompt -> exact image edit -> exact invoking chat"
say "Edit instruction without an attached image is stopped before FLUX."
say "Worker logs: /srv/ai-data/hermes-foto-jobs/<job-id>/worker.log"
say "Rollback: tools/rollback_hermes_foto_modern_stage28.sh"
