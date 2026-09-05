#!/usr/bin/env bash
set -euo pipefail

HERMES_HOME="/srv/ai-data/hermes"
HERMES_SOURCE="${HERMES_HOME}/hermes-agent"
HERMES_CONFIG="${HERMES_HOME}/config.yaml"
HERMES_RUN="${HERMES_SOURCE}/gateway/run.py"
HERMES_PYTHON="${HERMES_SOURCE}/venv/bin/python"
LIBEXEC_DIR="/usr/local/libexec/ai-server"
DISPATCH_DST="${LIBEXEC_DIR}/hermes_video_dispatch.py"
WRAPPER_DST="/usr/local/bin/hermes-video-dispatch"
BACKUP_DIR="${HERMES_HOME}/stage26-ltx23-direct-backup"

say(){ printf '%s\n' "$*"; }
section(){ printf '\n===== %s =====\n' "$1"; }
fail(){ say "FAIL: $*" >&2; exit 1; }
sha(){ sha256sum "$1" | awk '{print $1}'; }

section "ROLLBACK STAGE 26"
[[ -d "$BACKUP_DIR" ]] || fail "backup dir missing: $BACKUP_DIR"
[[ -r "$BACKUP_DIR/config.yaml" ]] || fail "config backup missing"
[[ -r "$BACKUP_DIR/gateway-run.py" ]] || fail "gateway/run.py backup missing"
[[ -r "$BACKUP_DIR/post-config.sha256" ]] || fail "post-config hash missing"
[[ -r "$BACKUP_DIR/post-gateway-run.sha256" ]] || fail "post-gateway hash missing"
[[ -r "$HERMES_CONFIG" ]] || fail "current Hermes config missing"
[[ -r "$HERMES_RUN" ]] || fail "current Hermes gateway/run.py missing"

section "REFUSE TO CLOBBER LATER MANUAL CHANGES"
expected_config="$(cat "$BACKUP_DIR/post-config.sha256")"
expected_run="$(cat "$BACKUP_DIR/post-gateway-run.sha256")"
current_config="$(sha "$HERMES_CONFIG")"
current_run="$(sha "$HERMES_RUN")"
[[ "$current_config" == "$expected_config" ]] || fail "config.yaml changed after Stage26; refusing automatic rollback"
[[ "$current_run" == "$expected_run" ]] || fail "gateway/run.py changed after Stage26; refusing automatic rollback"
say "PASS: managed files still match recorded Stage26 state"

section "RESTORE PRE-STAGE-26 HERMES STATE"
cp -a "$BACKUP_DIR/config.yaml" "$HERMES_CONFIG"
cp -a "$BACKUP_DIR/gateway-run.py" "$HERMES_RUN"
"$HERMES_PYTHON" -m py_compile "$HERMES_RUN" || fail "restored gateway/run.py does not compile"

restore_root_file(){
  local dst="$1" name="$2"
  if [[ -e "$BACKUP_DIR/$name.absent" ]]; then
    sudo rm -f "$dst"
    say "PASS: removed Stage26-created $dst"
  elif [[ -e "$BACKUP_DIR/$name" ]]; then
    sudo cp -a "$BACKUP_DIR/$name" "$dst"
    say "PASS: restored pre-stage $dst"
  else
    fail "no backup/absent marker for $dst"
  fi
}
restore_root_file "$DISPATCH_DST" "hermes_video_dispatch.py"
restore_root_file "$WRAPPER_DST" "hermes-video-dispatch"

section "RESTART HERMES ONLY"
systemctl --user restart hermes-gateway.service
[[ "$(systemctl --user is-active hermes-gateway.service 2>/dev/null || true)" == "active" ]] || fail "Hermes gateway did not restart cleanly"

section "DONE"
say "PASS: Stage26 rolled back to the exact pre-stage Hermes config and gateway source."
say "ComfyUI/LTX models, Ollama, AI Gateway and ventilation were not changed."
