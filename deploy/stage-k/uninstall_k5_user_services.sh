#!/usr/bin/env bash
set -Eeuo pipefail

TARGET="$HOME/.config/systemd/user"
CONTROL="$HOME/agent-control/stage-k"

systemctl --user disable --now   ai-platform-stage-k-daily.timer   ai-platform-stage-k-weekly.timer   ai-platform-stage-k-monitor.timer 2>/dev/null || true

for name in   ai-platform-stage-k-daily.service   ai-platform-stage-k-daily.timer   ai-platform-stage-k-weekly.service   ai-platform-stage-k-weekly.timer   ai-platform-stage-k-monitor.service   ai-platform-stage-k-monitor.timer; do
  rm -f "$TARGET/$name"
done

systemctl --user daemon-reload
rm -rf "$CONTROL"

echo "STAGE_K_K5_UNINSTALL_PASS=1"
echo "Backup data, manifests, status files and evidence were not deleted."
