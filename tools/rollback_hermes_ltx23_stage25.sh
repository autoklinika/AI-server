#!/usr/bin/env bash
set -euo pipefail

HERMES_HOME="/srv/ai-data/hermes"
HERMES_SKILL_DIR="${HERMES_HOME}/skills/wideo"
BACKUP_DIR="${HERMES_HOME}/stage25-ltx23-telegram-backup"
WRAPPER_DST="/usr/local/bin/generate-video-telegram"

say(){ printf '%s\n' "$*"; }
section(){ printf '\n===== %s =====\n' "$1"; }
fail(){ say "FAIL: $*" >&2; exit 1; }

[[ -d "$BACKUP_DIR" ]] || fail "Stage 25 backup not found: $BACKUP_DIR"

section "ROLLBACK HERMES LTX-2.3 STAGE 25"

if [[ -e "$BACKUP_DIR/generate-video-telegram" ]]; then
  sudo install -m 0755 "$BACKUP_DIR/generate-video-telegram" "$WRAPPER_DST"
  say "PASS: restored previous Telegram video wrapper"
elif [[ -e "$BACKUP_DIR/generate-video-telegram.absent" ]]; then
  sudo rm -f "$WRAPPER_DST"
  say "PASS: removed Stage 25 Telegram wrapper"
else
  fail "wrapper backup marker missing"
fi

if [[ -d "$BACKUP_DIR/skill-wideo" ]]; then
  rm -rf "$HERMES_SKILL_DIR"
  cp -a "$BACKUP_DIR/skill-wideo" "$HERMES_SKILL_DIR"
  say "PASS: restored previous Hermes wideo skill"
elif [[ -e "$BACKUP_DIR/skill-wideo.absent" ]]; then
  rm -rf "$HERMES_SKILL_DIR"
  say "PASS: removed Stage 25 Hermes wideo skill"
else
  fail "skill backup marker missing"
fi

section "RESTART HERMES GATEWAY"
systemctl --user restart hermes-gateway.service
systemctl --user is-active --quiet hermes-gateway.service || fail "Hermes gateway did not restart cleanly"
say "PASS: hermes-gateway.service active"

section "DONE"
say "PASS: Stage 25 routing rolled back"
say "LTX-2.3 model files and Stage 24 benchmark backend were intentionally retained."
