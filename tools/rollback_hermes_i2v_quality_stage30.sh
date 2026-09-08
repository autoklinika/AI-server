#!/usr/bin/env bash
set -euo pipefail

HERMES_HOME="/srv/ai-data/hermes"
BACKUP_DIR="${HERMES_HOME}/stage30-i2v-quality-backup"
LIBEXEC="/usr/local/libexec/ai-server"

DISPATCH_DST="${LIBEXEC}/hermes_video_dispatch.py"
DISPATCH_BASE_DST="${LIBEXEC}/hermes_video_dispatch_base.py"
QWEN30_DST="${LIBEXEC}/qwen_prompt_compiler_stage30.py"
GEN_DST="${LIBEXEC}/generate_ltx23.py"
GEN29_DST="${LIBEXEC}/generate_ltx23_stage29.py"
GEN_BASE_DST="${LIBEXEC}/generate_ltx23_base.py"

restore_optional(){
  local dst="$1" name="$2"
  if [[ -e "$BACKUP_DIR/$name.absent" ]]; then
    sudo rm -f "$dst"
  elif [[ -e "$BACKUP_DIR/$name" ]]; then
    sudo cp -a "$BACKUP_DIR/$name" "$dst"
  else
    echo "Missing Stage30 backup marker for $name" >&2
    exit 1
  fi
}

[[ -d "$BACKUP_DIR" ]] || {
  echo "Stage30 backup not found: $BACKUP_DIR" >&2
  exit 1
}

echo "===== ROLLBACK STAGE30 -> PRE-STAGE30 RUNTIME ====="
restore_optional "$DISPATCH_DST" "hermes_video_dispatch.py"
restore_optional "$DISPATCH_BASE_DST" "hermes_video_dispatch_base.py"
restore_optional "$QWEN30_DST" "qwen_prompt_compiler_stage30.py"
restore_optional "$GEN_DST" "generate_ltx23.py"
restore_optional "$GEN29_DST" "generate_ltx23_stage29.py"
restore_optional "$GEN_BASE_DST" "generate_ltx23_base.py"

systemctl --user restart hermes-gateway.service

echo "PASS: Stage30 runtime rolled back. Production main was never modified."
