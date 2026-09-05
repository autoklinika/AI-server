#!/usr/bin/env bash
set -euo pipefail

BACKUP_DIR="/srv/ai-data/hermes/stage24-ltx23-backup"
GENERATOR_DST="/usr/local/libexec/ai-server/generate_ltx23.py"
CLI_DST="/usr/local/bin/generate-video-ltx23"

say(){ printf '%s\n' "$*"; }
fail(){ say "FAIL: $*" >&2; exit 1; }
[[ -d "$BACKUP_DIR" ]] || fail "missing $BACKUP_DIR"

restore(){
  local dst="$1" name="$2"
  if [[ -e "$BACKUP_DIR/$name" ]]; then
    sudo cp -a "$BACKUP_DIR/$name" "$dst"
    say "PASS: restored $dst"
  elif [[ -e "$BACKUP_DIR/$name.absent" ]]; then
    sudo rm -f "$dst"
    say "PASS: removed Stage-24 file $dst"
  else
    fail "no backup marker for $dst"
  fi
}

restore "$GENERATOR_DST" "generate_ltx23.py"
restore "$CLI_DST" "generate-video-ltx23"

say "PASS: Stage 24 executable rollback complete"
say "LTX-2.3 weights are intentionally retained in ComfyUI models directories."
say "Wan2.2, FLUX, Hermes, Ollama and AI Gateway were not changed by this rollback."
