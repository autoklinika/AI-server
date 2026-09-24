#!/usr/bin/env bash
set -Eeuo pipefail

REPO="$HOME/AI-server"
SOURCE="$REPO/deploy/stage-k/systemd"
TARGET="$HOME/.config/systemd/user"
CONTROL="$HOME/agent-control/stage-k"
NOTIFY_SRC="$REPO/deploy/autopilot/notify_telegram.py"
NOTIFY_ENV="$HOME/.config/ai-platform/autopilot.env"

fail() {
  echo "STAGE_K_K5_INSTALL_FAIL=$*" >&2
  exit 1
}

[[ "$EUID" -ne 0 ]] || fail "run as harrypotter, not root"
[[ "$(id -un)" == "harrypotter" ]] || fail "unexpected user"
[[ -d "$REPO/.git" ]] || fail "main AI-server repo missing"
[[ "$(git -C "$REPO" branch --show-current)" == "main" ]] || fail "AI-server must be on main"
[[ -z "$(git -C "$REPO" status --porcelain)" ]] || fail "AI-server main working tree is dirty"
[[ "$(loginctl show-user "$USER" -p Linger --value)" == "yes" ]] || fail "systemd linger is not enabled"
[[ -f "$NOTIFY_ENV" ]] || fail "Telegram notifier env missing"

for f in   ai-platform-stage-k-daily.service   ai-platform-stage-k-daily.timer   ai-platform-stage-k-weekly.service   ai-platform-stage-k-weekly.timer   ai-platform-stage-k-monitor.service   ai-platform-stage-k-monitor.timer; do
  [[ -f "$SOURCE/$f" ]] || fail "missing unit: $f"
done

mkdir -p "$TARGET" "$CONTROL"
chmod 700 "$CONTROL"
install -m 700 "$NOTIFY_SRC" "$CONTROL/notify_telegram.py"

for f in "$SOURCE"/*; do
  install -m 600 "$f" "$TARGET/$(basename "$f")"
done

systemctl --user daemon-reload
systemctl --user enable --now   ai-platform-stage-k-daily.timer   ai-platform-stage-k-weekly.timer   ai-platform-stage-k-monitor.timer

systemctl --user start ai-platform-stage-k-monitor.service

echo "STAGE_K_K5_INSTALL_PASS=1"
systemctl --user list-timers --all --no-pager | grep 'ai-platform-stage-k' || true
