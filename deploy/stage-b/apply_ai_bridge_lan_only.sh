#!/usr/bin/env bash
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel)"
DROPIN=/etc/systemd/system/ai-bridge.service.d/zz-lan-only.conf

sudo install -d /etc/systemd/system/ai-bridge.service.d
sudo install -m 0644 \
  "$ROOT/deploy/systemd/stage-b/ai-bridge.service.d/zz-lan-only.conf" \
  "$DROPIN"

sudo systemctl daemon-reload
sudo systemctl restart ai-bridge.service

sleep 2

echo "===== LISTENER ====="
sudo ss -lntp | grep ':8080'

echo "===== HEALTH ====="
curl -fsS http://192.168.1.55:8080/health
echo
