#!/usr/bin/env bash
set -euo pipefail

sudo rm -f /etc/systemd/system/comfyui.service.d/zz-localhost-only.conf
sudo systemctl daemon-reload
sudo systemctl restart comfyui.service

sleep 3

echo "===== LISTENER ====="
sudo ss -lntp | grep ':8188'

echo "===== COMFYUI HTTP ====="
curl -fsS http://127.0.0.1:8188/system_stats >/dev/null
echo "COMFYUI ROLLBACK: PASS"
