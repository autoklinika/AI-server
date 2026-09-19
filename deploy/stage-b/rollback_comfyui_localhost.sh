#!/usr/bin/env bash
set -euo pipefail

sudo rm -f /etc/systemd/system/comfyui.service.d/zz-localhost-only.conf
sudo systemctl daemon-reload
sudo systemctl restart comfyui.service

for i in $(seq 1 30); do
  if curl -fsS http://127.0.0.1:8188/system_stats >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

echo "===== LISTENER ====="
sudo ss -lntp | grep ':8188'

echo "===== COMFYUI HTTP ====="
curl -fsS http://127.0.0.1:8188/system_stats >/dev/null
echo "COMFYUI ROLLBACK: PASS"
