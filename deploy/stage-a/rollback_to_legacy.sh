#!/usr/bin/env bash
set -euo pipefail

for u in ai-bridge.service ai-gateway.service ai-bridge-analysis.service; do
  sudo rm -f "/etc/systemd/system/$u.d/95-ai-platform-release.conf"
done

sudo systemctl daemon-reload
sudo systemctl restart ai-gateway.service
sudo systemctl restart ai-bridge.service

echo "===== ROLLBACK PATHS ====="
systemctl show ai-gateway.service -p WorkingDirectory --value
systemctl show ai-bridge.service -p WorkingDirectory --value

echo "===== HEALTH ====="
curl -fsS http://127.0.0.1:11435/health
echo
curl -fsS http://127.0.0.1:8080/health
echo

echo "ROLLBACK TO LEGACY: PASS"
