#!/usr/bin/env bash
set -euo pipefail

HERMES_HOME="/srv/ai-data/hermes"
HERMES_SOURCE="${HERMES_HOME}/hermes-agent"
HERMES_CONFIG="${HERMES_HOME}/config.yaml"
HERMES_RUN="${HERMES_SOURCE}/gateway/run.py"
HERMES_PYTHON="${HERMES_SOURCE}/venv/bin/python"
HERMES_EXPECTED_SHA="254158f4530cada634c4ef8f4cff93257c5b4f77"

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

section "STAGE 26 - DETERMINISTIC /WIDEO"
say "Route: Telegram /wideo -> Hermes exec quick_command -> detached local LTX worker -> hermes send MEDIA:<mp4>."
say "The LLM is removed from the critical execution/delivery path."
say "Existing /wideo skill stays installed only for menu/discovery; quick_commands has dispatch priority."
say "No ComfyUI/Ollama/AI-Gateway/ventilation configuration is changed."

section "PRECHECK"
[[ -d "$HERMES_SOURCE/.git" ]] || fail "Hermes source missing: $HERMES_SOURCE"
[[ -r "$HERMES_CONFIG" ]] || fail "Hermes config missing: $HERMES_CONFIG"
[[ -r "$HERMES_RUN" ]] || fail "Hermes gateway source missing: $HERMES_RUN"
[[ -x "$HERMES_PYTHON" ]] || fail "Hermes Python missing: $HERMES_PYTHON"
[[ -x "$LTX_BIN" ]] || fail "LTX generator missing/not executable: $LTX_BIN"
[[ -r "$DISPATCH_SRC" ]] || fail "missing source: $DISPATCH_SRC"
[[ -r "$WRAPPER_SRC" ]] || fail "missing source: $WRAPPER_SRC"
[[ -r "$PATCHER" ]] || fail "missing patcher: $PATCHER"
[[ "$(systemctl --user is-active hermes-gateway.service 2>/dev/null || true)" == "active" ]] || fail "hermes-gateway.service is not active"
[[ "$(systemctl is-active comfyui.service 2>/dev/null || true)" == "active" ]] || fail "comfyui.service is not active"

installed_sha="$(git -C "$HERMES_SOURCE" rev-parse HEAD)"
say "Hermes installed SHA: $installed_sha"
[[ "$installed_sha" == "$HERMES_EXPECTED_SHA" ]] || fail "unsupported Hermes checkout; expected $HERMES_EXPECTED_SHA"

"$HERMES_PYTHON" "$PATCHER" "$HERMES_RUN" --check || fail "Hermes quick-command dispatch is not patchable/safely recognized"

section "LTX PREFLIGHTS"
"$LTX_BIN" --preflight || fail "LTX standard preflight failed"
"$LTX_BIN" --upscale-2x --preflight || fail "LTX HQ preflight failed"

section "VERIFY PINNED HERMES DELIVERY CAPABILITIES"
"$HERMES_PYTHON" - "$HERMES_SOURCE" <<'PY'
from pathlib import Path
import sys
root=Path(sys.argv[1])
local=(root/'tools/environments/local.py').read_text(encoding='utf-8')
send=(root/'hermes_cli/send_cmd.py').read_text(encoding='utf-8')
if '_inject_session_context_env' not in local or 'HERMES_SESSION_CHAT_ID' not in local:
    raise SystemExit('FAIL: pinned Hermes lacks the session-context subprocess bridge')
if 'MEDIA:' not in send or 'send_message_tool' not in send:
    raise SystemExit('FAIL: pinned Hermes lacks native hermes send MEDIA delivery')
print('PASS: session routing context is bridged into quick-command subprocesses')
print('PASS: hermes send supports native MEDIA:<path> delivery')
PY

section "BACKUP PRE-STAGE-26 STATE"
mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"

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
backup_once "$HERMES_RUN" "gateway-run.py"
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

section "PATCH PINNED HERMES EXEC QUICK-COMMAND ARG FORWARDING"
"$HERMES_PYTHON" "$PATCHER" "$HERMES_RUN" || fail "failed to patch Hermes gateway/run.py"
"$HERMES_PYTHON" -m py_compile "$HERMES_RUN" || fail "patched Hermes gateway/run.py does not compile"
grep -q 'STAGE26_WIDEO_QUICK_ARGS' "$HERMES_RUN" || fail "Stage26 quick-command marker missing"
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
printf '%s\n' "$(sha "$HERMES_RUN")" > "$BACKUP_DIR/post-gateway-run.sha256"
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

grep -q 'STAGE26_WIDEO_QUICK_ARGS' "$HERMES_RUN" || fail "patched Hermes marker disappeared"
[[ "$(sha "$DISPATCH_DST")" == "$(cat "$BACKUP_DIR/post-dispatch.sha256")" ]] || fail "installed dispatcher changed unexpectedly"
[[ "$(sha "$WRAPPER_DST")" == "$(cat "$BACKUP_DIR/post-wrapper.sha256")" ]] || fail "installed wrapper changed unexpectedly"

section "DONE"
say "PASS: Stage26 deterministic /wideo cutover installed"
say "Standard: /wideo <opis> -> immediate ack -> LTX 640x384 -> MEDIA MP4 to invoking chat"
say "HQ:       /wideo hq <opis> -> immediate ack -> LTX 1280x768 -> MEDIA MP4 to invoking chat"
say "Qwen is NOT invoked for /wideo."
say "Worker logs: $JOB_ROOT/<job-id>/worker.log"
say "Rollback: tools/rollback_hermes_ltx23_direct_stage26.sh"
