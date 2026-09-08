#!/usr/bin/env bash
set -euo pipefail

HERMES_HOME="/srv/ai-data/hermes"
HERMES_SKILL_DIR="${HERMES_HOME}/skills/wideo"
BACKUP_DIR="${HERMES_HOME}/stage25-ltx23-telegram-backup"
WRAPPER_DST="/usr/local/bin/generate-video-telegram"
LTX_BIN="/usr/local/bin/generate-video-ltx23"

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
WRAPPER_SRC="${SCRIPT_DIR}/local_video/generate-video-telegram"
SKILL_SRC="${SCRIPT_DIR}/local_video/SKILL.md"

say(){ printf '%s\n' "$*"; }
section(){ printf '\n===== %s =====\n' "$1"; }
fail(){ say "FAIL: $*" >&2; exit 1; }

[[ -r "$WRAPPER_SRC" ]] || fail "missing $WRAPPER_SRC"
[[ -r "$SKILL_SRC" ]] || fail "missing $SKILL_SRC"
[[ -x "$LTX_BIN" ]] || fail "missing executable $LTX_BIN"
systemctl --user is-active --quiet hermes-gateway.service || fail "hermes-gateway.service is not active"

section "STAGE 25 HERMES LTX-2.3 CUTOVER"
say "Route: /wideo -> LTX-2.3 standard -> MP4 -> Telegram"
say "Route: /wideo hq -> LTX-2.3 two-stage x2 -> MP4 -> Telegram"
say "ComfyUI, Ollama, AI Gateway and ventilation configuration are not changed."

section "LTX PREFLIGHT"
"$LTX_BIN" --preflight
"$LTX_BIN" --upscale-2x --preflight

section "BACKUP CURRENT HERMES VIDEO ROUTING"
mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"

if [[ ! -e "$BACKUP_DIR/generate-video-telegram" && ! -e "$BACKUP_DIR/generate-video-telegram.absent" ]]; then
  if sudo test -e "$WRAPPER_DST"; then
    sudo cp -a "$WRAPPER_DST" "$BACKUP_DIR/generate-video-telegram"
    sudo chown "$(id -u):$(id -g)" "$BACKUP_DIR/generate-video-telegram"
    say "PASS: backed up $WRAPPER_DST"
  else
    : > "$BACKUP_DIR/generate-video-telegram.absent"
    say "INFO: wrapper did not exist before Stage 25"
  fi
else
  say "INFO: preserved existing Stage 25 wrapper backup"
fi

if [[ ! -e "$BACKUP_DIR/skill-wideo" && ! -e "$BACKUP_DIR/skill-wideo.absent" ]]; then
  if [[ -e "$HERMES_SKILL_DIR" ]]; then
    cp -a "$HERMES_SKILL_DIR" "$BACKUP_DIR/skill-wideo"
    say "PASS: backed up Hermes wideo skill"
  else
    : > "$BACKUP_DIR/skill-wideo.absent"
    say "INFO: wideo skill did not exist before Stage 25"
  fi
else
  say "INFO: preserved existing Stage 25 skill backup"
fi

section "INSTALL LTX TELEGRAM ROUTING"
sudo install -m 0755 "$WRAPPER_SRC" "$WRAPPER_DST"
mkdir -p "$HERMES_SKILL_DIR"
install -m 0644 "$SKILL_SRC" "$HERMES_SKILL_DIR/SKILL.md"
say "PASS: installed $WRAPPER_DST"
say "PASS: installed $HERMES_SKILL_DIR/SKILL.md"

section "WRAPPER RETURN-TO-CHAT SELFTEST"
TMPDIR_STAGE25="$(mktemp -d)"
trap 'rm -rf "$TMPDIR_STAGE25"' EXIT
FAKE_BIN="$TMPDIR_STAGE25/fake-ltx"
ARGS_LOG="$TMPDIR_STAGE25/args.log"
cat > "$FAKE_BIN" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$@" > "${HERMES_LTX_TEST_ARGS:?}"
if [[ " ${*} " == *" --upscale-2x "* ]]; then
  printf '%s\n' '/srv/ai-data/hermes-media/video/stage25-hq-selftest.mp4'
else
  printf '%s\n' '/srv/ai-data/hermes-media/video/stage25-standard-selftest.mp4'
fi
EOF
chmod 0755 "$FAKE_BIN"

STD_OUT="$(HERMES_LTX_VIDEO_BIN="$FAKE_BIN" HERMES_LTX_TEST_ARGS="$ARGS_LOG" "$WRAPPER_DST" -- 'red robot waves')"
[[ "$STD_OUT" == "/srv/ai-data/hermes-media/video/stage25-standard-selftest.mp4" ]] || fail "standard wrapper stdout is not a bare MP4 path"
! grep -Fxq -- '--upscale-2x' "$ARGS_LOG" || fail "standard mode unexpectedly enabled upscale"
grep -Fxq -- '--prompt' "$ARGS_LOG" || fail "standard mode did not pass --prompt"

HQ_OUT="$(HERMES_LTX_VIDEO_BIN="$FAKE_BIN" HERMES_LTX_TEST_ARGS="$ARGS_LOG" "$WRAPPER_DST" --hq -- 'red robot waves')"
[[ "$HQ_OUT" == "/srv/ai-data/hermes-media/video/stage25-hq-selftest.mp4" ]] || fail "HQ wrapper stdout is not a bare MP4 path"
grep -Fxq -- '--upscale-2x' "$ARGS_LOG" || fail "HQ mode did not enable --upscale-2x"
grep -Fxq -- '--prompt' "$ARGS_LOG" || fail "HQ mode did not pass --prompt"
say "PASS: standard and HQ routing preserve bare absolute MP4 stdout"

section "RESTART HERMES GATEWAY"
systemctl --user restart hermes-gateway.service
systemctl --user is-active --quiet hermes-gateway.service || fail "Hermes gateway did not restart cleanly"
say "PASS: hermes-gateway.service active"

section "FINAL CHECKS"
[[ -x "$WRAPPER_DST" ]] || fail "wrapper missing after install"
[[ -r "$HERMES_SKILL_DIR/SKILL.md" ]] || fail "skill missing after install"
grep -Fq '/wideo hq' "$HERMES_SKILL_DIR/SKILL.md" || fail "HQ mode missing from deployed skill"
grep -Fq 'Telegram' "$HERMES_SKILL_DIR/SKILL.md" || fail "return-to-chat contract missing from deployed skill"

section "DONE"
say "PASS: Hermes /wideo now uses LTX-2.3 standard"
say "PASS: Hermes /wideo hq now uses LTX-2.3 two-stage x2"
say "PASS: successful generator stdout remains the local MP4 path for native Telegram delivery"
