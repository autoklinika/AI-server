#!/usr/bin/env bash
set -euo pipefail

HERMES_HOME="/srv/ai-data/hermes"
HERMES_SOURCE="${HERMES_HOME}/hermes-agent"
HERMES_CONFIG="${HERMES_HOME}/config.yaml"
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
[[ -r "$HERMES_CONFIG" ]] || fail "current Hermes config missing"
[[ -x "$HERMES_PYTHON" ]] || fail "Hermes Python missing"

# New Stage26 records the exact patched module. Keep compatibility with the
# first Stage26 implementation which always patched gateway/run.py.
if [[ -r "$BACKUP_DIR/patch-target.rel" ]]; then
  PATCH_REL="$(cat "$BACKUP_DIR/patch-target.rel")"
  case "$PATCH_REL" in
    gateway/run.py|gateway/run_inbound.py) ;;
    *) fail "unsafe/unknown recorded Hermes patch target: $PATCH_REL" ;;
  esac
  HERMES_PATCH_TARGET="$HERMES_SOURCE/$PATCH_REL"
  PATCH_BACKUP="$BACKUP_DIR/gateway-dispatch.py"
  POST_PATCH_HASH="$BACKUP_DIR/post-gateway-dispatch.sha256"
else
  PATCH_REL="gateway/run.py"
  HERMES_PATCH_TARGET="$HERMES_SOURCE/$PATCH_REL"
  PATCH_BACKUP="$BACKUP_DIR/gateway-run.py"
  POST_PATCH_HASH="$BACKUP_DIR/post-gateway-run.sha256"
fi

[[ -r "$PATCH_BACKUP" ]] || fail "gateway dispatch backup missing: $PATCH_BACKUP"
[[ -r "$POST_PATCH_HASH" ]] || fail "post-stage gateway hash missing: $POST_PATCH_HASH"
[[ -r "$BACKUP_DIR/post-config.sha256" ]] || fail "post-config hash missing"
[[ -r "$HERMES_PATCH_TARGET" ]] || fail "current Hermes gateway module missing: $HERMES_PATCH_TARGET"

section "REFUSE TO CLOBBER LATER MANUAL CHANGES"
expected_config="$(cat "$BACKUP_DIR/post-config.sha256")"
expected_patch="$(cat "$POST_PATCH_HASH")"
current_config="$(sha "$HERMES_CONFIG")"
current_patch="$(sha "$HERMES_PATCH_TARGET")"
[[ "$current_config" == "$expected_config" ]] || fail "config.yaml changed after Stage26; refusing automatic rollback"
[[ "$current_patch" == "$expected_patch" ]] || fail "$PATCH_REL changed after Stage26; refusing automatic rollback"
say "PASS: managed files still match recorded Stage26 state"

section "RESTORE PRE-STAGE-26 HERMES STATE"
cp -a "$BACKUP_DIR/config.yaml" "$HERMES_CONFIG"
cp -a "$PATCH_BACKUP" "$HERMES_PATCH_TARGET"
"$HERMES_PYTHON" -m py_compile "$HERMES_PATCH_TARGET" || fail "restored $PATCH_REL does not compile"

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
say "PASS: Stage26 rolled back to the exact pre-stage Hermes config and $PATCH_REL."
say "ComfyUI/LTX models, Ollama, AI Gateway and ventilation were not changed."
