#!/usr/bin/env bash
set -Eeuo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || true)"
[[ -n "$REPO_ROOT" ]] || { echo "FAIL: run from AI-server repository"; exit 2; }

CHAT_ID=""
START=0
while (($#)); do
  case "$1" in
    --chat-id) CHAT_ID="${2:-}"; shift 2 ;;
    --start) START=1; shift ;;
    -h|--help)
      echo "usage: $0 --chat-id <telegram_private_chat_id> [--start]"
      exit 0
      ;;
    *) echo "FAIL: unknown argument: $1" >&2; exit 2 ;;
  esac
done

[[ "$CHAT_ID" =~ ^-?[0-9]+$ ]] || {
  echo "FAIL: --chat-id must be a numeric Telegram chat id" >&2
  exit 2
}

for cmd in git gh codex python3 tmux flock sudo; do
  command -v "$cmd" >/dev/null || { echo "FAIL: missing command: $cmd" >&2; exit 3; }
done

gh auth status >/dev/null 2>&1 || { echo "FAIL: gh is not authenticated"; exit 3; }

HERMES_ENV="/srv/ai-data/hermes/.env"
PRIVATE_DIR="$HOME/.config/ai-platform"
PRIVATE_ENV="$PRIVATE_DIR/autopilot.env"
CONTROL_DIR="$HOME/agent-control/stage-eh-master"
STATE_DIR="$HOME/agent-state/stage-eh"
WORKTREE="$HOME/agent-worktrees/stage-eh"
SESSION="stage-eh-master"
ROOT_BRIDGE="/usr/local/libexec/ai-platform/autopilot-root-exec"
LEGACY_UNIT="$HOME/.config/systemd/user/ai-stage-eh-agent.service"

# Stage D proved that direct user-systemd execution is incompatible with the
# local Codex/bubblewrap sandbox. Remove the legacy E-H launcher if an older
# bootstrap installed it, so it cannot restart unexpectedly after login/reboot.
if command -v systemctl >/dev/null 2>&1; then
  systemctl --user disable --now ai-stage-eh-agent.service >/dev/null 2>&1 || true
  rm -f "$LEGACY_UNIT"
  systemctl --user daemon-reload >/dev/null 2>&1 || true
fi

mkdir -p "$PRIVATE_DIR" "$CONTROL_DIR/prompts" "$STATE_DIR" "$HOME/agent-worktrees"
chmod 700 "$PRIVATE_DIR" "$CONTROL_DIR" "$STATE_DIR"

TOKEN="$(python3 - "$HERMES_ENV" <<'PY'
import sys
from pathlib import Path
p = Path(sys.argv[1])
if not p.is_file():
    raise SystemExit(2)
for raw in p.read_text(encoding="utf-8").splitlines():
    line = raw.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    k, v = line.split("=", 1)
    if k.strip() != "TELEGRAM_BOT_TOKEN":
        continue
    v = v.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in {"'", '"'}:
        v = v[1:-1]
    if v:
        print(v)
        raise SystemExit(0)
raise SystemExit(3)
PY
)" || {
  echo "FAIL: TELEGRAM_BOT_TOKEN not found in $HERMES_ENV" >&2
  exit 4
}

umask 077
tmp_env="$(mktemp "$PRIVATE_DIR/autopilot.env.XXXXXX")"
{
  printf 'TELEGRAM_BOT_TOKEN=%s\n' "$TOKEN"
  printf 'AI_AUTOPILOT_TELEGRAM_CHAT_ID=%s\n' "$CHAT_ID"
} > "$tmp_env"
chmod 600 "$tmp_env"
mv -f "$tmp_env" "$PRIVATE_ENV"
unset TOKEN

install -m 700 "$REPO_ROOT/deploy/autopilot/notify_telegram.py" "$CONTROL_DIR/notify_telegram.py"
install -m 700 "$REPO_ROOT/deploy/autopilot/run_stage.sh" "$CONTROL_DIR/run_stage.sh"
install -m 700 "$REPO_ROOT/deploy/autopilot/stage_eh_master.sh" "$CONTROL_DIR/master.sh"
install -m 600 "$REPO_ROOT"/deploy/autopilot/prompts/stage_*.md "$CONTROL_DIR/prompts/"

git -C "$REPO_ROOT" fetch origin main --prune
if [[ -e "$WORKTREE/.git" || -f "$WORKTREE/.git" ]]; then
  git -C "$WORKTREE" rev-parse --is-inside-work-tree >/dev/null
  [[ -z "$(git -C "$WORKTREE" status --porcelain)" ]] || {
    echo "FAIL: existing Stage E-H worktree is dirty: $WORKTREE" >&2
    exit 5
  }
  git -C "$WORKTREE" checkout --detach origin/main
else
  [[ ! -e "$WORKTREE" ]] || { echo "FAIL: path exists but is not a git worktree: $WORKTREE"; exit 5; }
  git -C "$REPO_ROOT" worktree add --detach "$WORKTREE" origin/main
fi

if ((START)); then
  [[ -x "$ROOT_BRIDGE" ]] || {
    echo "FAIL: privilege bridge missing. Run: bash deploy/autopilot/install_privilege_bridge.sh" >&2
    exit 8
  }
  [[ "$(sudo -n "$ROOT_BRIDGE" --self-test 2>/dev/null || true)" == "AUTOPILOT_ROOT_BRIDGE=READY" ]] || {
    echo "FAIL: privilege bridge is not authorized. Re-run installer." >&2
    exit 8
  }
fi

AI_AUTOPILOT_ENV="$PRIVATE_ENV" "$CONTROL_DIR/notify_telegram.py" INFO "E-H"   "Kanał alarmowy autopilota działa. Supervisor jest gotowy." || {
    echo "FAIL: test Telegram notification failed; supervisor was not started" >&2
    exit 6
  }

echo "READY: control=$CONTROL_DIR worktree=$WORKTREE state=$STATE_DIR"
if ((START)); then
  if tmux has-session -t "$SESSION" 2>/dev/null; then
    echo "FAIL: tmux session already exists: $SESSION" >&2
    exit 7
  fi
  launch="export PATH='$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin'; export AI_AUTOPILOT_ENV='$PRIVATE_ENV'; export AI_AUTOPILOT_CONTROL_DIR='$CONTROL_DIR'; export AI_AUTOPILOT_STATE_DIR='$STATE_DIR'; export AI_AUTOPILOT_WORKTREE='$WORKTREE'; exec '$CONTROL_DIR/master.sh' > '$STATE_DIR/master-console.log' 2>&1"
  tmux new-session -d -s "$SESSION" "$launch"
  echo "STARTED: tmux session $SESSION"
else
  echo "NOT STARTED: rerun with --start"
fi
