#!/usr/bin/env bash
set -euo pipefail

sudo rm -f /etc/systemd/system/ollama.service.d/zz-localhost-only.conf
sudo rm -f /etc/systemd/system/ollama.service.d/95-localhost-only.conf
sudo systemctl daemon-reload
sudo systemctl restart ollama.service
sudo systemctl restart ollama-preload.service

sleep 2

echo "===== LISTENER ====="
sudo ss -lntp | grep ':11434'

echo "===== GATEWAY HEALTH ====="
curl -fsS http://127.0.0.1:11435/health
echo
