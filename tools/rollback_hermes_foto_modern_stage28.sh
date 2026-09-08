#!/usr/bin/env bash
set -euo pipefail

HERMES_HOME="/srv/ai-data/hermes"
HERMES_SOURCE="${HERMES_HOME}/hermes-agent"
HERMES_CONFIG="${HERMES_HOME}/config.yaml"
HERMES_RUN="${HERMES_SOURCE}/gateway/run_inbound.py"
BACKUP_DIR="${HERMES_HOME}/stage28-foto-modern-backup"
DISPATCH_DST="/usr/local/bin/hermes-foto-dispatch"
COMPILER_DST="/usr/local/libexec/ai-server/hermes_foto_prompt_compiler.py"

say(){ printf '%s\n' "$*"; }
fail(){ say "FAIL: $*" >&2; exit 1; }

restore_optional(){
    local dst="$1" name="$2"
    if [ -e "$BACKUP_DIR/${name}.ABSENT" ]; then
        sudo rm -f "$dst"
    elif [ -r "$BACKUP_DIR/$name" ]; then
        sudo cp -a "$BACKUP_DIR/$name" "$dst"
    fi
}

[ -d "$BACKUP_DIR" ] || fail "Stage28 backup missing: $BACKUP_DIR"
[ -r "$BACKUP_DIR/run_inbound.py" ] || fail "Stage28 run_inbound.py backup missing"
[ -r "$BACKUP_DIR/config.yaml" ] || fail "Stage28 config backup missing"

cp -a "$BACKUP_DIR/run_inbound.py" "$HERMES_RUN"
cp -a "$BACKUP_DIR/config.yaml" "$HERMES_CONFIG"
restore_optional "$DISPATCH_DST" "hermes-foto-dispatch"
restore_optional "$COMPILER_DST" "hermes_foto_prompt_compiler.py"

systemctl --user restart hermes-gateway.service
[ "$(systemctl --user is-active hermes-gateway.service 2>/dev/null || true)" = "active" ] \
    || fail "Hermes failed to restart after rollback"

say "PASS: Stage28 /foto rolled back to exact pre-Stage28 state"
