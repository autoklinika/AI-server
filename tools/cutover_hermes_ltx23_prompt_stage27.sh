#!/usr/bin/env bash
set -euo pipefail

HERMES_HOME="/srv/ai-data/hermes"
HERMES_CONFIG="${HERMES_HOME}/config.yaml"
LIBEXEC="/usr/local/libexec/ai-server"
DISPATCH_DST="${LIBEXEC}/hermes_video_dispatch.py"
BASE_DST="${LIBEXEC}/hermes_video_dispatch_stage26.py"
QWEN_DST="${LIBEXEC}/qwen_prompt_compiler.py"
WRAPPER="/usr/local/bin/hermes-video-dispatch"
BACKUP_DIR="${HERMES_HOME}/stage27-ltx23-prompt-backup"
PYTHON="/usr/bin/python3"

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
BASE_SRC="${SCRIPT_DIR}/local_video/hermes_video_dispatch.py"
STAGE27_SRC="${SCRIPT_DIR}/local_video/hermes_video_dispatch_stage27.py"
QWEN_SRC="${SCRIPT_DIR}/local_video/qwen_prompt_compiler.py"

say(){ printf '%s\n' "$*"; }
section(){ printf '\n===== %s =====\n' "$1"; }
fail(){ say "FAIL: $*" >&2; exit 1; }
sha(){ sha256sum "$1" | awk '{print $1}'; }

section "STAGE 27 - QWEN PROMPT COMPILER"
say "Route: /wideo -> local Qwen prompt compiler -> LTX -> same Telegram chat."
say "If Qwen is bypassed, the chat MUST receive a warning before LTX starts."
say "No main/ComfyUI/Ollama/ventilation configuration is changed."

section "PRECHECK"
[[ -r "$BASE_SRC" ]] || fail "missing Stage26 base source"
[[ -r "$STAGE27_SRC" ]] || fail "missing Stage27 dispatcher"
[[ -r "$QWEN_SRC" ]] || fail "missing Qwen compiler"
[[ -x "$WRAPPER" ]] || fail "Stage26 dispatcher wrapper missing: $WRAPPER"
[[ -x "$DISPATCH_DST" ]] || fail "current Stage26 dispatcher missing: $DISPATCH_DST"
[[ -r "$HERMES_CONFIG" ]] || fail "Hermes config missing"
[[ "$(systemctl is-active ai-gateway.service 2>/dev/null || true)" == "active" ]] || fail "ai-gateway.service is not active"
grep -q '/usr/local/bin/hermes-video-dispatch' "$HERMES_CONFIG" || fail "Hermes /wideo quick command is not routed through Stage26 dispatcher"

"$PYTHON" -m py_compile "$BASE_SRC" "$STAGE27_SRC" "$QWEN_SRC"

section "BACKUP CURRENT PRODUCTION DISPATCHER"
mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"
if [[ ! -e "$BACKUP_DIR/hermes_video_dispatch.py" ]]; then
  sudo cp -a "$DISPATCH_DST" "$BACKUP_DIR/hermes_video_dispatch.py"
  say "PASS: backed up Stage26 dispatcher"
else
  say "INFO: preserving existing Stage27 dispatcher backup"
fi

backup_optional(){
  local src="$1" name="$2"
  if [[ -e "$BACKUP_DIR/$name" || -e "$BACKUP_DIR/$name.absent" ]]; then return; fi
  if sudo test -e "$src"; then
    sudo cp -a "$src" "$BACKUP_DIR/$name"
  else
    : > "$BACKUP_DIR/$name.absent"
  fi
}
backup_optional "$BASE_DST" "hermes_video_dispatch_stage26.py"
backup_optional "$QWEN_DST" "qwen_prompt_compiler.py"

section "INSTALL STAGE 27"
sudo install -d -m 0755 "$LIBEXEC"
sudo install -m 0755 "$BASE_SRC" "$BASE_DST"
sudo install -m 0644 "$QWEN_SRC" "$QWEN_DST"
sudo install -m 0755 "$STAGE27_SRC" "$DISPATCH_DST"
"$PYTHON" -m py_compile "$DISPATCH_DST" "$BASE_DST" "$QWEN_DST"

section "REAL LOCAL QWEN PREFLIGHT"
if ! "$PYTHON" "$DISPATCH_DST" --qwen-preflight; then
  say "FAIL: real Qwen prompt compiler preflight failed; restoring Stage26 dispatcher" >&2
  sudo cp -a "$BACKUP_DIR/hermes_video_dispatch.py" "$DISPATCH_DST"
  if [[ -e "$BACKUP_DIR/hermes_video_dispatch_stage26.py.absent" ]]; then sudo rm -f "$BASE_DST"; elif [[ -e "$BACKUP_DIR/hermes_video_dispatch_stage26.py" ]]; then sudo cp -a "$BACKUP_DIR/hermes_video_dispatch_stage26.py" "$BASE_DST"; fi
  if [[ -e "$BACKUP_DIR/qwen_prompt_compiler.py.absent" ]]; then sudo rm -f "$QWEN_DST"; elif [[ -e "$BACKUP_DIR/qwen_prompt_compiler.py" ]]; then sudo cp -a "$BACKUP_DIR/qwen_prompt_compiler.py" "$QWEN_DST"; fi
  exit 1
fi

section "RECORD POST-STATE"
printf '%s\n' "$(sha "$DISPATCH_DST")" > "$BACKUP_DIR/post-dispatch.sha256"
printf '%s\n' "$(sha "$BASE_DST")" > "$BACKUP_DIR/post-base.sha256"
printf '%s\n' "$(sha "$QWEN_DST")" > "$BACKUP_DIR/post-qwen.sha256"
chmod 600 "$BACKUP_DIR"/*.sha256

section "DONE"
say "PASS: Stage27 Qwen prompt compiler installed"
say "Qwen success: compiled English LTX prompt, no extra chat warning."
say "Qwen failure: mandatory Telegram warning, then original prompt fallback."
say "If the warning cannot be delivered, LTX does not start."
say "No Hermes restart required; quick command launches a fresh Python process per request."
say "Rollback: tools/rollback_hermes_ltx23_prompt_stage27.sh"
