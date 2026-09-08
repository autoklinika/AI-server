#!/usr/bin/env bash
set -euo pipefail

HERMES_HOME="/srv/ai-data/hermes"
HERMES_SOURCE="${HERMES_HOME}/hermes-agent"
HERMES_RUN="${HERMES_SOURCE}/gateway/run_inbound.py"
BACKUP_DIR="${HERMES_HOME}/stage29-video-duration-i2v-backup"
LIBEXEC="/usr/local/libexec/ai-server"
DISPATCH_DST="${LIBEXEC}/hermes_video_dispatch.py"
QWEN_DST="${LIBEXEC}/qwen_prompt_compiler.py"
GEN_DST="${LIBEXEC}/generate_ltx23.py"
GEN_BASE_DST="${LIBEXEC}/generate_ltx23_base.py"

say(){ printf '%s\n' "$*"; }
fail(){ say "FAIL: $*" >&2; exit 1; }
restore_optional(){
  local dst="$1" name="$2"
  if [[ -e "$BACKUP_DIR/$name.absent" ]]; then
    sudo rm -f "$dst"
  elif [[ -e "$BACKUP_DIR/$name" ]]; then
    sudo cp -a "$BACKUP_DIR/$name" "$dst"
  else
    fail "Stage29 backup incomplete: $name"
  fi
}

[[ -d "$BACKUP_DIR" ]] || fail "Stage29 backup missing: $BACKUP_DIR"
[[ -r "$BACKUP_DIR/run_inbound.py" ]] || fail "Stage29 run_inbound.py backup missing"

cp -a "$BACKUP_DIR/run_inbound.py" "$HERMES_RUN"
restore_optional "$DISPATCH_DST" "hermes_video_dispatch.py"
restore_optional "$QWEN_DST" "qwen_prompt_compiler.py"
restore_optional "$GEN_DST" "generate_ltx23.py"
restore_optional "$GEN_BASE_DST" "generate_ltx23_base.py"

systemctl --user restart hermes-gateway.service
[[ "$(systemctl --user is-active hermes-gateway.service 2>/dev/null || true)" == "active" ]] \
  || fail "Hermes failed to restart after Stage29 rollback"

grep -Fq 'STAGE29_WIDEO_MEDIA_ENV' "$HERMES_RUN" && fail "Stage29 Hermes patch still present after rollback"
say "PASS: Stage29 rolled back to exact pre-Stage29 video/Hermes state"
