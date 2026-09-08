#!/usr/bin/env bash
set -euo pipefail

HERMES_HOME="/srv/ai-data/hermes"
HERMES_SOURCE="${HERMES_HOME}/hermes-agent"
HERMES_RUN="${HERMES_SOURCE}/gateway/run_inbound.py"
HERMES_CONFIG="${HERMES_HOME}/config.yaml"
HERMES_STATE="${HERMES_HOME}/gateway_state.json"
HERMES_PYTHON="${HERMES_SOURCE}/venv/bin/python"
HERMES_EXPECTED_SHA="79445a496c86a19332ad786494b8384d2167e2d0"

LIBEXEC="/usr/local/libexec/ai-server"
DISPATCH_DST="${LIBEXEC}/hermes_video_dispatch.py"
QWEN_DST="${LIBEXEC}/qwen_prompt_compiler.py"
GEN_DST="${LIBEXEC}/generate_ltx23.py"
GEN_BASE_DST="${LIBEXEC}/generate_ltx23_base.py"
LTX_CLI="/usr/local/bin/generate-video-ltx23"
BACKUP_DIR="${HERMES_HOME}/stage29-video-duration-i2v-backup"
PYTHON="/usr/bin/python3"

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
DISPATCH_SRC="${SCRIPT_DIR}/local_video/hermes_video_dispatch_stage29.py"
QWEN_SRC="${SCRIPT_DIR}/local_video/qwen_prompt_compiler.py"
GEN_SRC="${SCRIPT_DIR}/local_video/generate_ltx23_stage29.py"
GEN_BASE_SRC="${SCRIPT_DIR}/local_video/generate_ltx23.py"
PATCHER="${SCRIPT_DIR}/patch_hermes_wideo_quick_media_stage29.py"

SUCCESS=0
MUTATED=0
say(){ printf '%s\n' "$*"; }
section(){ printf '\n===== %s =====\n' "$1"; }
fail(){ say "FAIL: $*" >&2; exit 1; }

restore_optional(){
  local dst="$1" name="$2"
  if [[ -e "$BACKUP_DIR/$name.absent" ]]; then
    sudo rm -f "$dst"
  elif [[ -e "$BACKUP_DIR/$name" ]]; then
    sudo cp -a "$BACKUP_DIR/$name" "$dst"
  fi
}

restore_from_backup(){
  [[ -d "$BACKUP_DIR" ]] || return 0
  [[ -r "$BACKUP_DIR/run_inbound.py" ]] && cp -a "$BACKUP_DIR/run_inbound.py" "$HERMES_RUN"
  restore_optional "$DISPATCH_DST" "hermes_video_dispatch.py"
  restore_optional "$QWEN_DST" "qwen_prompt_compiler.py"
  restore_optional "$GEN_DST" "generate_ltx23.py"
  restore_optional "$GEN_BASE_DST" "generate_ltx23_base.py"
  systemctl --user restart hermes-gateway.service >/dev/null 2>&1 || true
}

cleanup(){
  rc=$?
  trap - EXIT INT TERM
  if [[ "$SUCCESS" -ne 1 && "$MUTATED" -eq 1 ]]; then
    echo
    echo "===== AUTOMATIC ROLLBACK ====="
    restore_from_backup
  fi
  exit "$rc"
}
trap cleanup EXIT INT TERM

backup_optional(){
  local src="$1" name="$2"
  if [[ -e "$BACKUP_DIR/$name" || -e "$BACKUP_DIR/$name.absent" ]]; then return; fi
  if sudo test -e "$src"; then sudo cp -a "$src" "$BACKUP_DIR/$name"; else : > "$BACKUP_DIR/$name.absent"; fi
}

wait_hermes(){
  "$HERMES_PYTHON" - "$HERMES_STATE" <<'PY'
from pathlib import Path
import json, sys, time
path=Path(sys.argv[1]); deadline=time.monotonic()+90; last=None
while time.monotonic()<deadline:
    try: last=json.loads(path.read_text(encoding='utf-8'))
    except Exception: time.sleep(1); continue
    p=last.get('platforms') or {}
    if (last.get('gateway_state')=='running'
        and (p.get('telegram') or {}).get('state')=='connected'
        and (p.get('api_server') or {}).get('state')=='connected'):
        print('PASS: Hermes gateway running, Telegram connected, API connected'); raise SystemExit(0)
    time.sleep(1)
print(json.dumps(last, ensure_ascii=False, indent=2) if last else '<no gateway state>')
raise SystemExit(1)
PY
}

section "STAGE 29 - LONGER + IMAGE-TO-VIDEO"
say "Syntax: /wideo [hq] [1s..6s] <opis>."
say "If the same Telegram message contains an image, it becomes the exact first frame for LTX-2.3."
say "No cloud inference; /foto and ventilation are not changed."

section "PRECHECK"
[[ -d "$HERMES_SOURCE/.git" ]] || fail "Hermes source missing"
[[ -x "$HERMES_PYTHON" ]] || fail "Hermes Python missing"
[[ -r "$HERMES_RUN" ]] || fail "gateway/run_inbound.py missing"
[[ -r "$HERMES_CONFIG" ]] || fail "Hermes config missing"
[[ -x "$LTX_CLI" ]] || fail "LTX CLI missing"
[[ -r "$DISPATCH_SRC" && -r "$QWEN_SRC" && -r "$GEN_SRC" && -r "$GEN_BASE_SRC" && -r "$PATCHER" ]] || fail "Stage29 source file missing"
[[ "$(systemctl is-active comfyui.service 2>/dev/null || true)" == "active" ]] || fail "comfyui.service is not active"
[[ "$(systemctl is-active ai-gateway.service 2>/dev/null || true)" == "active" ]] || fail "ai-gateway.service is not active"
[[ "$(systemctl --user is-active hermes-gateway.service 2>/dev/null || true)" == "active" ]] || fail "hermes-gateway.service is not active"

installed_sha="$(git -C "$HERMES_SOURCE" rev-parse HEAD)"
say "Hermes installed SHA: $installed_sha"
[[ "$installed_sha" == "$HERMES_EXPECTED_SHA" ]] || fail "unsupported Hermes checkout"
grep -Fq 'STAGE26_WIDEO_ROUTE_ENV' "$HERMES_RUN" || fail "Stage26 exact route bridge missing"
grep -Fq 'STAGE28_FOTO_MEDIA_ENV' "$HERMES_RUN" || fail "Stage28 /foto media bridge missing"
grep -q '/usr/local/bin/hermes-video-dispatch' "$HERMES_CONFIG" || fail "/wideo is not routed through deterministic dispatcher"
grep -q '/usr/local/bin/hermes-foto-dispatch' "$HERMES_CONFIG" || fail "/foto Stage28 quick command missing"

"$PYTHON" -m py_compile "$DISPATCH_SRC" "$QWEN_SRC" "$GEN_SRC" "$GEN_BASE_SRC" "$PATCHER"
patch_state="$("$HERMES_PYTHON" "$PATCHER" "$HERMES_RUN" --check)" || fail "Stage29 Hermes patch unsupported: $patch_state"
say "Hermes /wideo image bridge: $patch_state"

section "BACKUP PRE-STAGE-29 STATE"
mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"
if [[ ! -e "$BACKUP_DIR/run_inbound.py" ]]; then
  cp --preserve=mode,timestamps "$HERMES_RUN" "$BACKUP_DIR/run_inbound.py"
  backup_optional "$DISPATCH_DST" "hermes_video_dispatch.py"
  backup_optional "$QWEN_DST" "qwen_prompt_compiler.py"
  backup_optional "$GEN_DST" "generate_ltx23.py"
  backup_optional "$GEN_BASE_DST" "generate_ltx23_base.py"
  say "PASS: Stage29 reversible backup created"
else
  say "INFO: preserving existing pre-Stage29 backup"
fi

section "PATCH MODERN HERMES /WIDEO IMAGE BRIDGE"
MUTATED=1
"$HERMES_PYTHON" "$PATCHER" "$HERMES_RUN"
"$HERMES_PYTHON" -m py_compile "$HERMES_RUN"
grep -Fq 'STAGE29_WIDEO_MEDIA_ENV' "$HERMES_RUN" || fail "Stage29 media bridge marker missing"
say "PASS: exact current-turn image path is bridged only for /wideo"

section "INSTALL STAGE 29 RUNTIME"
sudo install -d -m 0755 "$LIBEXEC"
sudo install -m 0755 "$GEN_BASE_SRC" "$GEN_BASE_DST"
sudo install -m 0755 "$GEN_SRC" "$GEN_DST"
sudo install -m 0644 "$QWEN_SRC" "$QWEN_DST"
sudo install -m 0755 "$DISPATCH_SRC" "$DISPATCH_DST"

"$PYTHON" - "$DISPATCH_DST" "$QWEN_DST" "$GEN_DST" "$GEN_BASE_DST" <<'PY'
from pathlib import Path
import sys
for raw in sys.argv[1:]:
    p=Path(raw); compile(p.read_text(encoding='utf-8'), str(p), 'exec')
print('PASS: installed Stage29 Python syntax valid (no bytecode write)')
PY

section "LTX NODE/MODEL PREFLIGHTS"
"$LTX_CLI" --preflight || fail "standard LTX preflight failed"
"$LTX_CLI" --preflight --upscale-2x || fail "HQ LTX preflight failed"
"$LTX_CLI" --i2v-preflight || fail "image-to-video node preflight failed"
"$LTX_CLI" --i2v-preflight --upscale-2x || fail "HQ image-to-video node preflight failed"
say "PASS: text/video, longer-frame and image-to-video runtime prerequisites available"

section "REAL LOCAL QWEN PREFLIGHT"
"$PYTHON" "$DISPATCH_DST" --qwen-preflight || fail "Stage29 Qwen prompt compiler preflight failed"

section "RESTART HERMES ONLY"
systemctl --user restart hermes-gateway.service
wait_hermes || fail "Hermes failed to reconnect after Stage29 patch"

section "POSTCHECK"
"$HERMES_PYTHON" - "$HERMES_CONFIG" <<'PY'
from pathlib import Path
import sys,yaml
cfg=yaml.safe_load(Path(sys.argv[1]).read_text(encoding='utf-8')) or {}
qc=cfg.get('quick_commands') or {}
print('quick_commands.wideo:', qc.get('wideo'))
print('quick_commands.foto:', qc.get('foto'))
assert (qc.get('wideo') or {}).get('command') == '/usr/local/bin/hermes-video-dispatch'
assert (qc.get('foto') or {}).get('command') == '/usr/local/bin/hermes-foto-dispatch'
print('PASS: /wideo Stage29 route active; /foto preserved')
PY

SUCCESS=1
MUTATED=0
section "DONE"
say "PASS: Stage29 longer + image-to-video installed"
say "Examples:"
say "  /wideo 4s <opis>"
say "  /wideo hq 4s <opis>"
say "  attach image + caption '/wideo 4s <ruch od pierwszej klatki>'"
say "Rollback: tools/rollback_hermes_video_duration_i2v_stage29.sh"
