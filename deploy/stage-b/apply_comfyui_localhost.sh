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
echo "COMFYUI: PASS"
