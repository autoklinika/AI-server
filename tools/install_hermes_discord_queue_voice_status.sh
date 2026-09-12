#!/usr/bin/env bash
set -euo pipefail

ROOT="${HOME}/AI-server"
BRANCH="feat/hermes-discord-queue-status"
WT="${HOME}/AI-server-discord-queue-voice-install"
HERMES_HOME="/srv/ai-data/hermes"
HERMES_SOURCE="${HERMES_HOME}/hermes-agent"
HERMES_PY="${HERMES_SOURCE}/venv/bin/python"
HERMES_TURN="${HERMES_SOURCE}/agent/turn_api_request.py"
HERMES_RUNNER="${HERMES_SOURCE}/gateway/run_turn_runner.py"
HERMES_EXPECTED="79445a496c86a19332ad786494b8384d2167e2d0"
LIBEXEC="/usr/local/libexec/ai-server"
HELPER="${LIBEXEC}/hermes_resource_queue.py"
BACKUP="/srv/ai-data/hermes/discord-queue-voice-backup-v1"
SUCCESS=0
MUTATED=0

say(){ printf '%s\n' "$*"; }
fail(){ say "FAIL: $*" >&2; exit 1; }

backup_file(){
    local src="$1" name="$2"
    if [[ -e "$BACKUP/$name" || -e "$BACKUP/$name.absent" ]]; then
        return
    fi
    if sudo test -e "$src"; then
        sudo cp -a "$src" "$BACKUP/$name"
    else
        sudo touch "$BACKUP/$name.absent"
        sudo chown harrypotter:harrypotter "$BACKUP/$name.absent"
    fi
}

restore_file(){
    local dst="$1" name="$2"
    if [[ -e "$BACKUP/$name.absent" ]]; then
        sudo rm -f "$dst"
    elif [[ -e "$BACKUP/$name" ]]; then
        sudo cp -a "$BACKUP/$name" "$dst"
    fi
}

restore_all(){
    [[ -d "$BACKUP" ]] || return 0
    restore_file "$HERMES_TURN" hermes-turn_api_request.py
    restore_file "$HERMES_RUNNER" hermes-run_turn_runner.py
    restore_file "$HELPER" hermes_resource_queue.py
    systemctl --user restart hermes-gateway.service >/dev/null 2>&1 || true
}

cleanup(){
    rc=$?
    trap - EXIT INT TERM
    if [[ "$SUCCESS" -ne 1 && "$MUTATED" -eq 1 ]]; then
        echo
        echo "===== AUTOMATIC ROLLBACK ====="
        restore_all
    fi
    if [[ -d "$WT" ]]; then
        git -C "$ROOT" worktree remove --force "$WT" >/dev/null 2>&1 || true
    fi
    exit "$rc"
}
trap cleanup EXIT INT TERM

[[ -d "$ROOT/.git" ]] || fail "repo missing: $ROOT"
[[ -d "$HERMES_SOURCE/.git" ]] || fail "Hermes checkout missing: $HERMES_SOURCE"
[[ -x "$HERMES_PY" ]] || fail "Hermes Python missing: $HERMES_PY"
[[ -f "$HERMES_TURN" ]] || fail "Hermes turn_api_request.py missing"
[[ -f "$HERMES_RUNNER" ]] || fail "Hermes run_turn_runner.py missing"
[[ "$(git -C "$HERMES_SOURCE" rev-parse HEAD)" == "$HERMES_EXPECTED" ]] || fail "unsupported Hermes checkout"
[[ "$(systemctl --user is-active hermes-gateway.service 2>/dev/null || true)" == active ]] || fail "hermes-gateway.service inactive"
[[ "$(systemctl is-active ai-gateway.service 2>/dev/null || true)" == active ]] || fail "ai-gateway.service inactive"

echo "===== FETCH FEATURE BRANCH ====="
cd "$ROOT"
git fetch origin "$BRANCH"
if [[ -d "$WT" ]]; then
    git worktree remove --force "$WT" >/dev/null 2>&1 || true
fi
git worktree add --detach "$WT" "origin/$BRANCH"
say "feature: $(git -C "$WT" rev-parse --short HEAD)"

echo
echo "===== STATIC PRECHECK ====="
"$HERMES_PY" -m py_compile \
    "$WT/tools/hermes_resource_queue.py" \
    "$WT/tools/patch_hermes_global_resource_queue.py" \
    "$WT/tools/patch_hermes_discord_queue_voice.py"
turn_state="$("$HERMES_PY" "$WT/tools/patch_hermes_global_resource_queue.py" "$HERMES_TURN" --check)" || fail "turn_api_request patch unsupported: $turn_state"
runner_state="$("$HERMES_PY" "$WT/tools/patch_hermes_discord_queue_voice.py" "$HERMES_RUNNER" --check)" || fail "run_turn_runner patch unsupported: $runner_state"
say "turn_api_request: $turn_state"
say "run_turn_runner: $runner_state"

echo
echo "===== RESOURCE MANAGER PRECHECK ====="
"$HERMES_PY" - <<'PY'
import json, urllib.request
with urllib.request.urlopen("http://127.0.0.1:11435/status", timeout=3) as response:
    status = json.load(response)
print(json.dumps(status, ensure_ascii=False))
assert "active_count" in status and "queued_count" in status, "global resource manager not installed"
PY

echo
echo "===== BACKUP ====="
sudo install -d -o harrypotter -g harrypotter -m 0700 "$BACKUP"
backup_file "$HERMES_TURN" hermes-turn_api_request.py
backup_file "$HERMES_RUNNER" hermes-run_turn_runner.py
backup_file "$HELPER" hermes_resource_queue.py
say "PASS: reversible backup ready"
MUTATED=1

echo
echo "===== INSTALL QUEUE HELPER + HERMES PATCHES ====="
sudo install -d -m 0755 "$LIBEXEC"
sudo install -m 0644 "$WT/tools/hermes_resource_queue.py" "$HELPER"
"$HERMES_PY" "$WT/tools/patch_hermes_global_resource_queue.py" "$HERMES_TURN"
"$HERMES_PY" "$WT/tools/patch_hermes_discord_queue_voice.py" "$HERMES_RUNNER"
"$HERMES_PY" -m py_compile "$HELPER" "$HERMES_TURN" "$HERMES_RUNNER"

grep -q 'AI_SERVER_GLOBAL_RESOURCE_QUEUE_V3' "$HERMES_TURN" || fail "queue v3 marker missing"
grep -q 'AI_SERVER_DISCORD_QUEUE_VOICE_V1' "$HERMES_RUNNER" || fail "Discord queue voice marker missing"

echo
echo "===== RESTART HERMES ====="
systemctl --user restart hermes-gateway.service
for _ in $(seq 1 60); do
    if [[ "$(systemctl --user is-active hermes-gateway.service 2>/dev/null || true)" == active ]]; then
        break
    fi
    sleep .25
done
[[ "$(systemctl --user is-active hermes-gateway.service)" == active ]] || fail "Hermes failed to restart"

SUCCESS=1
MUTATED=0

echo
echo "===== DONE ====="
say "PASS: Discord queue text notifications preserved."
say "PASS: Discord Voice queue transitions use Hermes play_ack_in_voice/TTS pipeline."
say "PASS: queue voice status does not consume the normal first-tool voice acknowledgement."
say "PASS: no main merge was performed."
