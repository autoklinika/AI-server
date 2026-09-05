#!/usr/bin/env bash
set -euo pipefail

HERMES_HOME="/srv/ai-data/hermes"
HERMES_SKILL_DIR="${HERMES_HOME}/skills/wideo"
BACKUP_DIR="${HERMES_HOME}/stage23-local-video-backup"
GENERATOR_DST="/usr/local/libexec/ai-server/generate_video.py"
CLI_DST="/usr/local/bin/generate-video"
TELEGRAM_DST="/usr/local/bin/generate-video-telegram"

say() { printf '%s\n' "$*"; }
section() { printf '\n===== %s =====\n' "$1"; }
fail() { say "FAIL: $*" >&2; exit 1; }

[[ -d "$BACKUP_DIR" ]] || fail "Stage-23 backup directory missing: $BACKUP_DIR"

section "STAGE-23 LOCAL VIDEO ROLLBACK"
say "Restoring wrappers and Hermes skill to their exact pre-Stage-23 state."
say "Downloaded Wan2.2 model files are intentionally retained."

restore_root_file() {
  local dst="$1" name="$2"
  if [[ -e "${BACKUP_DIR}/${name}" ]]; then
    sudo cp -a "${BACKUP_DIR}/${name}" "$dst"
    say "PASS: restored $dst"
  elif [[ -e "${BACKUP_DIR}/${name}.absent" ]]; then
    sudo rm -f "$dst"
    say "PASS: removed Stage-23 file $dst"
  else
    fail "missing backup/absence marker for $dst"
  fi
}

section "RESTORE EXECUTABLES"
restore_root_file "$GENERATOR_DST" "generate_video.py"
restore_root_file "$CLI_DST" "generate-video"
restore_root_file "$TELEGRAM_DST" "generate-video-telegram"

section "RESTORE HERMES SKILL"
if [[ -d "${BACKUP_DIR}/skill-wideo" ]]; then
  rm -rf "$HERMES_SKILL_DIR"
  cp -a "${BACKUP_DIR}/skill-wideo" "$HERMES_SKILL_DIR"
  say "PASS: restored pre-Stage-23 wideo skill"
elif [[ -e "${BACKUP_DIR}/skill-wideo.absent" ]]; then
  rm -rf "$HERMES_SKILL_DIR"
  say "PASS: removed Stage-23 wideo skill"
else
  fail "missing skill backup/absence marker"
fi

section "RESTART HERMES"
systemctl --user restart hermes-gateway.service
systemctl --user is-active --quiet hermes-gateway.service || fail "Hermes gateway did not restart cleanly"
say "PASS: Hermes gateway active"

section "VERIFY COMFYUI UNTOUCHED"
if systemctl is-active --quiet comfyui.service 2>/dev/null || systemctl --user is-active --quiet comfyui.service 2>/dev/null; then
  say "PASS: comfyui.service remains active"
else
  say "WARN: comfyui.service is not active"
fi

section "DONE"
say "PASS: Stage-23 local video rollback completed"
say "Wan2.2 weights were left in the existing ComfyUI model directories for reuse."
say "The production AI Gateway, Ollama, ventilation routing and FLUX image pipeline were not modified by rollback."
