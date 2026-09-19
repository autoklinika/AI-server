#!/usr/bin/env bash
set -euo pipefail

RELEASE_ID="${1:?usage: $0 RELEASE_ID}"
ROOT="$(git rev-parse --show-toplevel)"
RELEASE="/opt/ai-platform/releases/$RELEASE_ID"

fail_rollback() {
  echo "CUTOVER FAILED — rolling back to legacy runtime"
  "$ROOT/deploy/stage-a/rollback_to_legacy.sh" || true
  exit 1
}

[ -x "$RELEASE/services/ai-bridge/.venv/bin/ai-bridge" ] || fail_rollback
[ -x "$RELEASE/services/ai-gateway/.venv/bin/python" ] || fail_rollback
[ -f "$RELEASE/RELEASE" ] || fail_rollback

if systemctl is-active --quiet ai-bridge-analysis.service; then
  echo "Analysis job is currently running. Abort."
  exit 1
fi

sudo systemctl stop ai-bridge-analysis.timer
trap 'echo "CUTOVER ERROR"; "'"$ROOT"'/deploy/stage-a/rollback_to_legacy.sh"' ERR

echo "===== ACTIVATE $RELEASE_ID ====="

sudo ln -sfn "$RELEASE" /opt/ai-platform/current

for u in ai-bridge.service ai-gateway.service ai-bridge-analysis.service; do
  sudo install -d "/etc/systemd/system/$u.d"
  sudo install -m 0644 \
    "$ROOT/deploy/systemd/stage-a/$u.d/95-ai-platform-release.conf" \
    "/etc/systemd/system/$u.d/95-ai-platform-release.conf"
done

sudo systemctl daemon-reload
sudo systemctl restart ai-gateway.service
sudo systemctl restart ai-bridge.service

sleep 2

echo "===== PATHS ====="
systemctl show ai-gateway.service -p WorkingDirectory --value
systemctl show ai-bridge.service -p WorkingDirectory --value

echo "===== HEALTH ====="
curl -fsS http://127.0.0.1:11435/health || fail_rollback
echo
curl -fsS http://127.0.0.1:8080/health || fail_rollback
echo

echo "===== CURRENT ====="
readlink -f /opt/ai-platform/current

sudo systemctl start ai-bridge-analysis.timer
trap - ERR

echo "CUTOVER: PASS"
