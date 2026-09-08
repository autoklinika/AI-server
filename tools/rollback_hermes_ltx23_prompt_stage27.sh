#!/usr/bin/env bash
set -euo pipefail

HERMES_HOME="/srv/ai-data/hermes"
LIBEXEC="/usr/local/libexec/ai-server"
DISPATCH_DST="${LIBEXEC}/hermes_video_dispatch.py"
BASE_DST="${LIBEXEC}/hermes_video_dispatch_stage26.py"
QWEN_DST="${LIBEXEC}/qwen_prompt_compiler.py"
BACKUP_DIR="${HERMES_HOME}/stage27-ltx23-prompt-backup"

say(){ printf '%s\n' "$*"; }
section(){ printf '\n===== %s =====\n' "$1"; }
fail(){ say "FAIL: $*" >&2; exit 1; }
sha(){ sha256sum "$1" | awk '{print $1}'; }

section "ROLLBACK STAGE 27"
[[ -r "$BACKUP_DIR/hermes_video_dispatch.py" ]] || fail "Stage27 dispatcher backup missing"
[[ -r "$BACKUP_DIR/post-dispatch.sha256" ]] || fail "Stage27 post-state missing"
[[ -r "$DISPATCH_DST" ]] || fail "current dispatcher missing"

section "REFUSE TO CLOBBER LATER CHANGES"
[[ "$(sha "$DISPATCH_DST")" == "$(cat "$BACKUP_DIR/post-dispatch.sha256")" ]] || fail "dispatcher changed after Stage27; refusing automatic rollback"
if [[ -e "$BASE_DST" && -r "$BACKUP_DIR/post-base.sha256" ]]; then
  [[ "$(sha "$BASE_DST")" == "$(cat "$BACKUP_DIR/post-base.sha256")" ]] || fail "Stage26 base module changed after Stage27"
fi
if [[ -e "$QWEN_DST" && -r "$BACKUP_DIR/post-qwen.sha256" ]]; then
  [[ "$(sha "$QWEN_DST")" == "$(cat "$BACKUP_DIR/post-qwen.sha256")" ]] || fail "Qwen compiler changed after Stage27"
fi
say "PASS: managed files still match Stage27 post-state"

section "RESTORE STAGE 26"
sudo cp -a "$BACKUP_DIR/hermes_video_dispatch.py" "$DISPATCH_DST"

restore_optional(){
  local dst="$1" name="$2"
  if [[ -e "$BACKUP_DIR/$name.absent" ]]; then
    sudo rm -f "$dst"
    say "PASS: removed Stage27-created $dst"
  elif [[ -e "$BACKUP_DIR/$name" ]]; then
    sudo cp -a "$BACKUP_DIR/$name" "$dst"
    say "PASS: restored pre-Stage27 $dst"
  fi
}
restore_optional "$BASE_DST" "hermes_video_dispatch_stage26.py"
restore_optional "$QWEN_DST" "qwen_prompt_compiler.py"

/usr/bin/python3 -m py_compile "$DISPATCH_DST"

section "DONE"
say "PASS: Stage27 rolled back; deterministic Stage26 /wideo delivery remains installed."
say "No Hermes restart was required."
