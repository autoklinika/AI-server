#!/usr/bin/env bash
set -euo pipefail

HERMES_HOME="/srv/ai-data/hermes"
HERMES_SOURCE="${HERMES_HOME}/hermes-agent"
HERMES_CONFIG="${HERMES_HOME}/config.yaml"
HERMES_PYTHON="${HERMES_SOURCE}/venv/bin/python"

# Both layouts were verified for Stage 26:
# - 254158f...: older monolithic gateway/run.py
# - 79445a4...: modular gateway/run_inbound.py (current production checkout)
HERMES_SUPPORTED_SHA_OLD="254158f4530cada634c4ef8f4cff93257c5b4f77"
HERMES_SUPPORTED_SHA_CURRENT="79445a496c86a19332ad786494b8384d2167e2d0"

LIBEXEC_DIR="/usr/local/libexec/ai-server"
DISPATCH_DST="${LIBEXEC_DIR}/hermes_video_dispatch.py"
WRAPPER_DST="/usr/local/bin/hermes-video-dispatch"
LTX_BIN="/usr/local/bin/generate-video-ltx23"
JOB_ROOT="/srv/ai-data/hermes-video-jobs"
BACKUP_DIR="${HERMES_HOME}/stage26-ltx23-direct-backup"

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
DISPATCH_SRC="${SCRIPT_DIR}/local_video/hermes_video_dispatch.py"
WRAPPER_SRC="${SCRIPT_DIR}/local_video/hermes-video-dispatch"
PATCHER="${SCRIPT_DIR}/patch_hermes_quick_command_args_stage26.py"

say(){ printf '%s\n' "$*"; }
section(){ printf '\n===== %s =====\n' "$1"; }
fail(){ say "FAIL: $*" >&2; exit 1; }
sha(){ sha256sum "$1" | awk '{print $1}'; }

select_gateway_patch_target(){
  local candidate
  for candidate in \
    "$HERMES_SOURCE/gateway/run_inbound.py" \
    "$HERMES_SOURCE/gateway/run.py"
  do
    [[ -r "$candidate" ]] || continue
    if grep -q '_hm_run_exec_quick_command' "$candidate" \
      && grep -q 'qcmd.get("command", "")' "$candidate"; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done
  return 1
}

section "STAGE 26 - DETERMINISTIC /WIDEO"
say "Route: Telegram /wideo -> Hermes exec quick_command -> detached local LTX worker -> hermes send MEDIA:<mp4>."
say "The LLM is removed from the critical execution/delivery path."
say "Existing /wideo skill stays installed only for menu/discovery; quick_commands has dispatch priority."
say "No ComfyUI/Ollama/AI-Gateway/ventilation configuration is changed."

section "PRECHECK"
[[ -d "$HERMES_SOURCE/.git" ]] || fail "Hermes source missing: $HERMES_SOURCE"
[[ -r "$HERMES_CONFIG" ]] || fail "Hermes config missing: $HERMES_CONFIG"
[[ -x "$HERMES_PYTHON" ]] || fail "Hermes Python missing: $HERMES_PYTHON"
[[ -x "$LTX_BIN" ]] || fail "LTX generator missing/not executable: $LTX_BIN"
[[ -r "$DISPATCH_SRC" ]] || fail "missing source: $DISPATCH_SRC"
[[ -r "$WRAPPER_SRC" ]] || fail "missing source: $WRAPPER_SRC"
[[ -r "$PATCHER" ]] || fail "missing patcher: $PATCHER"
[[ "$(systemctl --user is-active hermes-gateway.service 2>/dev/null || true)" == "active" ]] || fail "hermes-gateway.service is not active"
[[ "$(systemctl is-active comfyui.service 2>/dev/null || true)" == "active" ]] || fail "comfyui.service is not active"

installed_sha="$(git -C "$HERMES_SOURCE" rev-parse HEAD)"
say "Hermes installed SHA: $installed_sha"
case "$installed_sha" in
  "$HERMES_SUPPORTED_SHA_OLD"|"$HERMES_SUPPORTED_SHA_CURRENT") ;;
  *) fail "unsupported Hermes checkout: $installed_sha; supported: $HERMES_SUPPORTED_SHA_OLD or $HERMES_SUPPORTED_SHA_CURRENT" ;;
esac

HERMES_PATCH_TARGET="$(select_gateway_patch_target)" || fail "could not locate supported Hermes gateway quick-command dispatch module"
HERMES_PATCH_REL="${HERMES_PATCH_TARGET#${HERMES_SOURCE}/}"
say "Hermes gateway dispatch: $HERMES_PATCH_REL"

"$HERMES_PYTHON" "$PATCHER" "$HERMES_PATCH_TARGET" --check || fail "Hermes quick-command dispatch is not patchable/safely recognized"

section "LTX PREFLIGHTS"
"$LTX_BIN" --preflight || fail "LTX standard preflight failed"
"$LTX_BIN" --upscale-2x --preflight || fail "LTX HQ preflight failed"

section "VERIFY HERMES DELIVERY CAPABILITIES"
"$HERMES_PYTHON" - "$HERMES_SOURCE" "$HERMES_PATCH_TARGET" <<'PY'
from pathlib import Path
import sys
root=Path(sys.argv[1])
quick=Path(sys.argv[2]).read_text(encoding='utf-8')
local=(root/'tools/environments/local.py').read_text(encoding='utf-8')
send=(root/'hermes_cli/send_cmd.py').read_text(encoding='utf-8')
session_path=root/'gateway/session_context.py'
session=session_path.read_text(encoding='utf-8') if session_path.exists() else ''

# Current modular Hermes keeps the literal HERMES_SESSION_* names in
# gateway/session_context.py while tools/environments/local.py consumes _VAR_MAP.
# Older Hermes may contain the literals directly in local.py. Accept either layout,
# but require the complete semantic chain used by exec quick_commands.
if '_inject_session_context_env' not in local:
    raise SystemExit('FAIL: Hermes lacks the session-context subprocess bridge function')
if 'build_subprocess_env' not in local:
    raise SystemExit('FAIL: Hermes lacks sanitized quick-command subprocess env factory')
if 'build_subprocess_env' not in quick:
    raise SystemExit('FAIL: Hermes exec quick-command path does not use build_subprocess_env')

session_names = local + '\n' + session
for name in ('HERMES_SESSION_PLATFORM', 'HERMES_SESSION_CHAT_ID', 'HERMES_SESSION_THREAD_ID'):
    if name not in session_names:
        raise SystemExit(f'FAIL: Hermes session routing variable missing: {name}')

if session:
    if '_VAR_MAP' not in session or 'ContextVar' not in session:
        raise SystemExit('FAIL: current Hermes session_context.py lacks expected ContextVar routing map')
    if '_inject_session_context_env' in local and '_VAR_MAP' not in local:
        # The bridge imports _VAR_MAP from gateway.session_context in current Hermes.
        if 'gateway.session_context' not in local:
            raise SystemExit('FAIL: session bridge does not source gateway.session_context')

if 'MEDIA:' not in send or 'send_message_tool' not in send:
    raise SystemExit('FAIL: Hermes lacks native hermes send MEDIA delivery')
if 'platform:chat_id:thread_id' not in send:
    raise SystemExit('FAIL: hermes send target syntax is not the verified platform:chat[:thread] form')

print('PASS: exec quick_commands use build_subprocess_env')
print('PASS: session platform/chat/thread routing is bridged into subprocesses')
print('PASS: hermes send supports native MEDIA:<path> delivery to exact chat/thread')
PY

section "BACKUP PRE-STAGE-26 STATE"
mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"

# Never mix backups from different Hermes source layouts/checkouts.
if [[ -e "$BACKUP_DIR/patch-target.rel" ]]; then
  recorded_rel="$(cat "$BACKUP_DIR/patch-target.rel")"
  [[ "$recorded_rel" == "$HERMES_PATCH_REL" ]] || fail "existing Stage26 backup targets $recorded_rel, current Hermes requires $HERMES_PATCH_REL; rollback/clear old Stage26 state first"
elif [[ -e "$BACKUP_DIR/gateway-run.py" || -e "$BACKUP_DIR/gateway-dispatch.py" ]]; then
  fail "legacy/incomplete Stage26 backup exists without patch-target.rel; inspect/rollback before reinstalling"
else
  printf '%s\n' "$HERMES_PATCH_REL" > "$BACKUP_DIR/patch-target.rel"
  chmod 600 "$BACKUP_DIR/patch-target.rel"
fi

backup_once(){
  local src="$1" name="$2"
  if [[ -e "$BACKUP_DIR/$name" || -e "$BACKUP_DIR/$name.absent" ]]; then
    say "INFO: preserving existing backup marker for $src"
    return
  fi
  if [[ -e "$src" ]]; then
    cp -a "$src" "$BACKUP_DIR/$name"
    say "PASS: backed up $src"
  else
    : > "$BACKUP_DIR/$name.absent"
    say "INFO: recorded absent pre-stage file $src"
  fi
}

backup_once "$HERMES_CONFIG" "config.yaml"
backup_once "$HERMES_PATCH_TARGET" "gateway-dispatch.py"
if sudo test -e "$DISPATCH_DST"; then
  sudo cp -a "$DISPATCH_DST" "$BACKUP_DIR/hermes_video_dispatch.py"
elif [[ ! -e "$BACKUP_DIR/hermes_video_dispatch.py.absent" && ! -e "$BACKUP_DIR/hermes_video_dispatch.py" ]]; then
  : > "$BACKUP_DIR/hermes_video_dispatch.py.absent"
fi
if sudo test -e "$WRAPPER_DST"; then
  sudo cp -a "$WRAPPER_DST" "$BACKUP_DIR/hermes-video-dispatch"
elif [[ ! -e "$BACKUP_DIR/hermes-video-dispatch.absent" && ! -e "$BACKUP_DIR/hermes-video-dispatch" ]]; then
  : > "$BACKUP_DIR/hermes-video-dispatch.absent"
fi

section "PATCH HERMES EXEC QUICK-COMMAND ARG FORWARDING"
"$HERMES_PYTHON" "$PATCHER" "$HERMES_PATCH_TARGET" || fail "failed to patch $HERMES_PATCH_REL"
"$HERMES_PYTHON" -m py_compile "$HERMES_PATCH_TARGET" || fail "patched $HERMES_PATCH_REL does not compile"
grep -q 'STAGE26_WIDEO_QUICK_ARGS' "$HERMES_PATCH_TARGET" || fail "Stage26 quick-command marker missing"
say "PASS: /wideo arguments will be passed as one shell-quoted argv item"

section "INSTALL DIRECT VIDEO DISPATCHER"
sudo install -d -m 0755 "$LIBEXEC_DIR"
sudo install -m 0755 "$DISPATCH_SRC" "$DISPATCH_DST"
sudo install -m 0755 "$WRAPPER_SRC" "$WRAPPER_DST"
mkdir -p "$JOB_ROOT"
chmod 700 "$JOB_ROOT"
[[ -x "$WRAPPER_DST" ]] || fail "dispatcher wrapper is not executable"
[[ -x "$DISPATCH_DST" ]] || fail "dispatcher backend is not executable"

section "CONFIGURE /WIDEO QUICK COMMAND"
"$HERMES_PYTHON" - "$HERMES_CONFIG" "$WRAPPER_DST" <<'PY'
from pathlib import Path
import os, sys, tempfile, yaml
path=Path(sys.argv[1]); wrapper=sys.argv[2]
cfg=yaml.safe_load(path.read_text(encoding='utf-8')) or {}
if not isinstance(cfg, dict):
    raise SystemExit('FAIL: config root is not a mapping')
quick=cfg.setdefault('quick_commands', {})
if not isinstance(quick, dict):
    raise SystemExit('FAIL: quick_commands exists but is not a mapping')
quick['wideo']={'type':'exec','command':wrapper}
fd,tmp=tempfile.mkstemp(prefix=path.name+'.stage26.', dir=str(path.parent), text=True)
try:
    with os.fdopen(fd,'w',encoding='utf-8') as f:
        yaml.safe_dump(cfg,f,allow_unicode=True,sort_keys=False)
        f.flush(); os.fsync(f.fileno())
    os.chmod(tmp,path.stat().st_mode)
    try: os.chown(tmp,path.stat().st_uid,path.stat().st_gid)
    except PermissionError: pass
    os.replace(tmp,path)
finally:
    try: os.unlink(tmp)
    except FileNotFoundError: pass
print('PASS: quick_commands.wideo ->', wrapper)
PY

section "RECORD MANAGED POST-STATE"
printf '%s\n' "$(sha "$HERMES_CONFIG")" > "$BACKUP_DIR/post-config.sha256"
printf '%s\n' "$(sha "$HERMES_PATCH_TARGET")" > "$BACKUP_DIR/post-gateway-dispatch.sha256"
printf '%s\n' "$(sha "$DISPATCH_DST")" > "$BACKUP_DIR/post-dispatch.sha256"
printf '%s\n' "$(sha "$WRAPPER_DST")" > "$BACKUP_DIR/post-wrapper.sha256"
chmod 600 "$BACKUP_DIR"/*.sha256

section "RESTART HERMES ONLY"
systemctl --user restart hermes-gateway.service
[[ "$(systemctl --user is-active hermes-gateway.service 2>/dev/null || true)" == "active" ]] || fail "Hermes gateway did not restart cleanly"

section "POSTCHECK"
"$HERMES_PYTHON" - "$HERMES_CONFIG" "$WRAPPER_DST" <<'PY'
from pathlib import Path
import sys,yaml
cfg=yaml.safe_load(Path(sys.argv[1]).read_text(encoding='utf-8')) or {}
expected={'type':'exec','command':sys.argv[2]}
actual=(cfg.get('quick_commands') or {}).get('wideo')
print('quick_commands.wideo:', actual)
if actual != expected:
    raise SystemExit(f'FAIL: unexpected quick_commands.wideo: {actual!r}')
print('PASS: /wideo is a zero-LLM exec quick command')
PY

grep -q 'STAGE26_WIDEO_QUICK_ARGS' "$HERMES_PATCH_TARGET" || fail "patched Hermes marker disappeared"
[[ "$(sha "$HERMES_PATCH_TARGET")" == "$(cat "$BACKUP_DIR/post-gateway-dispatch.sha256")" ]] || fail "$HERMES_PATCH_REL changed unexpectedly after restart"
[[ "$(sha "$DISPATCH_DST")" == "$(cat "$BACKUP_DIR/post-dispatch.sha256")" ]] || fail "installed dispatcher changed unexpectedly"
[[ "$(sha "$WRAPPER_DST")" == "$(cat "$BACKUP_DIR/post-wrapper.sha256")" ]] || fail "installed wrapper changed unexpectedly"

section "DONE"
say "PASS: Stage26 deterministic /wideo cutover installed"
say "Hermes checkout: $installed_sha"
say "Patched module:  $HERMES_PATCH_REL"
say "Standard: /wideo <opis> -> immediate ack -> LTX 640x384 -> MEDIA MP4 to invoking chat"
say "HQ:       /wideo hq <opis> -> immediate ack -> LTX 1280x768 -> MEDIA MP4 to invoking chat"
say "Qwen is NOT invoked for /wideo."
say "Worker logs: $JOB_ROOT/<job-id>/worker.log"
say "Rollback: tools/rollback_hermes_ltx23_direct_stage26.sh"
