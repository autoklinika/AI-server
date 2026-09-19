#!/usr/bin/env bash
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel)"
DROPIN=/etc/systemd/system/ollama.service.d/zz-localhost-only.conf
OLD_DROPIN=/etc/systemd/system/ollama.service.d/95-localhost-only.conf

sudo install -d /etc/systemd/system/ollama.service.d
sudo rm -f "$OLD_DROPIN"
sudo install -m 0644 \
  "$ROOT/deploy/systemd/stage-b/ollama.service.d/zz-localhost-only.conf" \
  "$DROPIN"

sudo systemctl daemon-reload
sudo systemctl restart ollama.service
sudo systemctl restart ollama-preload.service

sleep 2

echo "===== LISTENER ====="
sudo ss -lntp | grep ':11434'

echo "===== GATEWAY HEALTH ====="
curl -fsS http://127.0.0.1:11435/health
echo
