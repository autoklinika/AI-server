#!/usr/bin/env bash
set -euo pipefail

HERMES_HOME="/srv/ai-data/hermes"
HERMES_SOURCE="${HERMES_HOME}/hermes-agent"
HERMES_CONFIG="${HERMES_HOME}/config.yaml"
HERMES_STATE="${HERMES_HOME}/gateway_state.json"
HERMES_PYTHON="${HERMES_SOURCE}/venv/bin/python"

LIBEXEC="/usr/local/libexec/ai-server"
DISPATCH_DST="${LIBEXEC}/hermes_video_dispatch.py"
DISPATCH_BASE_DST="${LIBEXEC}/hermes_video_dispatch_base.py"
QWEN_BASE_DST="${LIBEXEC}/qwen_prompt_compiler.py"
QWEN30_DST="${LIBEXEC}/qwen_prompt_compiler_stage30.py"
GEN_DST="${LIBEXEC}/generate_ltx23.py"
GEN29_DST="${LIBEXEC}/generate_ltx23_stage29.py"
GEN_BASE_DST="${LIBEXEC}/generate_ltx23_base.py"
LTX_CLI="/usr/local/bin/generate-video-ltx23"

BACKUP_DIR="${HERMES_HOME}/stage30-i2v-quality-backup"
PYTHON="/usr/bin/python3"

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
DISPATCH_SRC="${SCRIPT_DIR}/local_video/hermes_video_dispatch_stage30.py"
DISPATCH_BASE_SRC="${SCRIPT_DIR}/local_video/hermes_video_dispatch.py"
QWEN30_SRC="${SCRIPT_DIR}/local_video/qwen_prompt_compiler_stage30.py"
GEN_SRC="${SCRIPT_DIR}/local_video/generate_ltx23_stage30.py"
GEN29_SRC="${SCRIPT_DIR}/local_video/generate_ltx23_stage29.py"
GEN_BASE_SRC="${SCRIPT_DIR}/local_video/generate_ltx23.py"

SUCCESS=0
MUTATED=0

say(){ printf '%s\n' "$*"; }
section(){ printf '\n===== %s =====\n' "$1"; }
fail(){ say "FAIL: $*" >&2; exit 1; }

backup_optional(){
  local src="$1" name="$2"
  if [[ -e "$BACKUP_DIR/$name" || -e "$BACKUP_DIR/$name.absent" ]]; then
    return
  fi
  if sudo test -e "$src"; then
    sudo cp -a "$src" "$BACKUP_DIR/$name"
  else
    : > "$BACKUP_DIR/$name.absent"
  fi
}

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
  restore_optional "$DISPATCH_DST" "hermes_video_dispatch.py"
  restore_optional "$DISPATCH_BASE_DST" "hermes_video_dispatch_base.py"
  restore_optional "$QWEN30_DST" "qwen_prompt_compiler_stage30.py"
  restore_optional "$GEN_DST" "generate_ltx23.py"
  restore_optional "$GEN29_DST" "generate_ltx23_stage29.py"
  restore_optional "$GEN_BASE_DST" "generate_ltx23_base.py"
  systemctl --user restart hermes-gateway.service >/dev/null 2>&1 || true
}

cleanup(){
  rc=$?
  trap - EXIT INT TERM
  if [[ "$SUCCESS" -ne 1 && "$MUTATED" -eq 1 ]]; then
    echo
    echo "===== AUTOMATIC ROLLBACK STAGE30 ====="
    restore_from_backup
  fi
  exit "$rc"
}
trap cleanup EXIT INT TERM

wait_hermes(){
  "$HERMES_PYTHON" - "$HERMES_STATE" <<'PY'
from pathlib import Path
import json, sys, time
path=Path(sys.argv[1]); deadline=time.monotonic()+90; last=None
while time.monotonic()<deadline:
    try:
        last=json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        time.sleep(1); continue
    p=last.get('platforms') or {}
    if (last.get('gateway_state')=='running'
        and (p.get('telegram') or {}).get('state')=='connected'
        and (p.get('api_server') or {}).get('state')=='connected'):
        print('PASS: Hermes gateway running, Telegram connected, API connected')
        raise SystemExit(0)
    time.sleep(1)
print(json.dumps(last, ensure_ascii=False, indent=2) if last else '<no gateway state>')
raise SystemExit(1)
PY
}

section "STAGE 30 - I2V QUALITY"
say "Feature branch runtime only. Stage29 main is not modified."
say "I2V changes: Lanczos center crop, compression=18, gentler first anchor,"
say "HQ 0.70 -> 1.00 anchoring, conservative Qwen I2V prompts and motion profiles."
say "T2V sampler/sigmas/CFG and tiled VAE remain Stage29."

section "PRECHECK"
[[ -d "$HERMES_SOURCE/.git" ]] || fail "Hermes source missing"
[[ -x "$HERMES_PYTHON" ]] || fail "Hermes Python missing"
[[ -r "$HERMES_CONFIG" ]] || fail "Hermes config missing"
[[ -x "$LTX_CLI" ]] || fail "LTX CLI missing"
[[ -r "$QWEN_BASE_DST" ]] || fail "Stage29 Qwen base runtime missing"
[[ -r "$DISPATCH_SRC" && -r "$DISPATCH_BASE_SRC" && -r "$QWEN30_SRC" ]] || fail "Stage30 dispatcher/compiler source missing"
[[ -r "$GEN_SRC" && -r "$GEN29_SRC" && -r "$GEN_BASE_SRC" ]] || fail "Stage30 generator source missing"
[[ "$(systemctl is-active comfyui.service 2>/dev/null || true)" == "active" ]] || fail "comfyui.service is not active"
[[ "$(systemctl is-active ai-gateway.service 2>/dev/null || true)" == "active" ]] || fail "ai-gateway.service is not active"
[[ "$(systemctl --user is-active hermes-gateway.service 2>/dev/null || true)" == "active" ]] || fail "hermes-gateway.service is not active"
grep -q '/usr/local/bin/hermes-video-dispatch' "$HERMES_CONFIG" || fail "/wideo deterministic dispatcher route missing"
grep -q '/usr/local/bin/hermes-foto-dispatch' "$HERMES_CONFIG" || fail "/foto route missing"

"$PYTHON" -m py_compile \
  "$DISPATCH_SRC" "$DISPATCH_BASE_SRC" "$QWEN30_SRC" \
  "$GEN_SRC" "$GEN29_SRC" "$GEN_BASE_SRC"

section "BACKUP CURRENT STAGE29 RUNTIME"
mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"
backup_optional "$DISPATCH_DST" "hermes_video_dispatch.py"
backup_optional "$DISPATCH_BASE_DST" "hermes_video_dispatch_base.py"
backup_optional "$QWEN30_DST" "qwen_prompt_compiler_stage30.py"
backup_optional "$GEN_DST" "generate_ltx23.py"
backup_optional "$GEN29_DST" "generate_ltx23_stage29.py"
backup_optional "$GEN_BASE_DST" "generate_ltx23_base.py"
say "PASS: reversible Stage29 runtime backup ready"

section "INSTALL STAGE30 RUNTIME"
MUTATED=1
sudo install -d -m 0755 "$LIBEXEC"

# Keep the old deterministic dispatch primitives under a non-active module name,
# then make only the Stage30 dispatcher active.
sudo install -m 0644 "$DISPATCH_BASE_SRC" "$DISPATCH_BASE_DST"
sudo install -m 0644 "$QWEN30_SRC" "$QWEN30_DST"
sudo install -m 0755 "$DISPATCH_SRC" "$DISPATCH_DST"

# Stage30 builds on the proven Stage29 graph; preserve both dependencies by name.
sudo install -m 0755 "$GEN_BASE_SRC" "$GEN_BASE_DST"
sudo install -m 0755 "$GEN29_SRC" "$GEN29_DST"
sudo install -m 0755 "$GEN_SRC" "$GEN_DST"

"$PYTHON" - "$DISPATCH_DST" "$DISPATCH_BASE_DST" "$QWEN30_DST" "$GEN_DST" "$GEN29_DST" "$GEN_BASE_DST" <<'PY'
from pathlib import Path
import sys
for raw in sys.argv[1:]:
    p=Path(raw)
    compile(p.read_text(encoding='utf-8'), str(p), 'exec')
print('PASS: installed Stage30 Python syntax valid')
PY

section "LTX STAGE30 PREFLIGHTS"
"$LTX_CLI" --preflight || fail "standard LTX preflight failed"
"$LTX_CLI" --preflight --upscale-2x || fail "HQ LTX preflight failed"
"$LTX_CLI" --i2v-preflight || fail "Stage30 I2V preflight failed"
"$LTX_CLI" --i2v-preflight --upscale-2x || fail "Stage30 HQ I2V preflight failed"
say "PASS: Stage30 requires core ImageScale + Stage29 I2V/tiled-VAE nodes"

section "REAL LOCAL QWEN I2V PREFLIGHT"
"$PYTHON" "$DISPATCH_DST" --qwen-preflight || fail "Stage30 Qwen I2V compiler preflight failed"

section "RESTART HERMES ONLY"
systemctl --user restart hermes-gateway.service
wait_hermes || fail "Hermes failed to reconnect after Stage30 install"

SUCCESS=1
MUTATED=0

section "DONE"
say "PASS: Stage30 I2V quality runtime installed"
say "Stage29 production source on main was not changed."
say "Default I2V: compression=18, standard strength=0.85."
say "Default HQ I2V: first strength=0.70, reinject strength=1.00."
say "Examples:"
say "  attach image + /wideo 4s motion=subtle <ruch>"
say "  attach image + /wideo hq 4s motion=normal <ruch>"
say "Rollback: tools/rollback_hermes_i2v_quality_stage30.sh"
