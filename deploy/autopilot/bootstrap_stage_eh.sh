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

for cmd in git gh codex python3 systemctl flock; do
  command -v "$cmd" >/dev/null || { echo "FAIL: missing command: $cmd" >&2; exit 3; }
done

gh auth status >/dev/null 2>&1 || { echo "FAIL: gh is not authenticated"; exit 3; }

HERMES_ENV="/srv/ai-data/hermes/.env"
PRIVATE_DIR="$HOME/.config/ai-platform"
PRIVATE_ENV="$PRIVATE_DIR/autopilot.env"
CONTROL_DIR="$HOME/agent-control/stage-eh-master"
STATE_DIR="$HOME/agent-state/stage-eh"
WORKTREE="$HOME/agent-worktrees/stage-eh"
UNIT_DIR="$HOME/.config/systemd/user"
UNIT="$UNIT_DIR/ai-stage-eh-agent.service"

mkdir -p "$PRIVATE_DIR" "$CONTROL_DIR/prompts" "$STATE_DIR" "$HOME/agent-worktrees" "$UNIT_DIR"
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

cat > "$UNIT" <<EOF
[Unit]
Description=AI Platform autonomous Stage E-H supervisor
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
WorkingDirectory=$WORKTREE
Environment=HOME=$HOME
Environment=AI_AUTOPILOT_ENV=$PRIVATE_ENV
ExecStart=$CONTROL_DIR/master.sh
TimeoutStartSec=infinity
PrivateTmp=true
NoNewPrivileges=false

[Install]
WantedBy=default.target
EOF

systemctl --user daemon-reload
systemctl --user enable ai-stage-eh-agent.service >/dev/null

AI_AUTOPILOT_ENV="$PRIVATE_ENV" "$CONTROL_DIR/notify_telegram.py" INFO "E-H"   "Kanał alarmowy autopilota działa. Supervisor jest gotowy." || {
    echo "FAIL: test Telegram notification failed; supervisor was not started" >&2
    exit 6
  }

echo "READY: control=$CONTROL_DIR worktree=$WORKTREE state=$STATE_DIR"
if ((START)); then
  systemctl --user start --no-block ai-stage-eh-agent.service
  echo "STARTED: ai-stage-eh-agent.service"
else
  echo "NOT STARTED: rerun with --start or use systemctl --user start ai-stage-eh-agent.service"
fi
