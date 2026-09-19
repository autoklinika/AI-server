#!/usr/bin/env bash
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel)"
DROPIN=/etc/systemd/system/comfyui.service.d/zz-localhost-only.conf

sudo install -d /etc/systemd/system/comfyui.service.d
sudo install -m 0644 \
  "$ROOT/deploy/systemd/stage-b/comfyui.service.d/zz-localhost-only.conf" \
  "$DROPIN"

sudo systemctl daemon-reload
sudo systemctl restart comfyui.service

sleep 3

echo "===== LISTENER ====="
sudo ss -lntp | grep ':8188'

echo "===== COMFYUI HTTP ====="
curl -fsS http://127.0.0.1:8188/system_stats >/dev/null
echo "COMFYUI: PASS"
