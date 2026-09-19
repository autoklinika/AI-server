#!/usr/bin/env bash
set -euo pipefail

sudo rm -f /etc/systemd/system/ai-bridge.service.d/zz-lan-only.conf
sudo systemctl daemon-reload
sudo systemctl restart ai-bridge.service

sleep 2

curl -fsS http://127.0.0.1:8080/health
echo
echo "AI BRIDGE BIND ROLLBACK: PASS"
