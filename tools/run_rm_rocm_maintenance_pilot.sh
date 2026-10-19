#!/usr/bin/env bash
# Local operator action only. Requires sudo authentication to stop AI services.
set -euo pipefail
BASE=/srv/ai-data/evaluation/rocm-managed-worker-adapter-dev-20261017
cd "$BASE"
echo "RM GPU pilot: stopping AI workloads and new scheduled analysis."
sudo systemctl stop ai-bridge-analysis.timer ai-bridge.service ai-gateway.service comfyui.service ollama.service
echo "Confirming core GPU services are inactive..."
for unit in ai-bridge-analysis.timer ai-bridge.service ai-gateway.service comfyui.service ollama.service; do
  if [[ "$(systemctl is-active "$unit" 2>/dev/null || true)" != inactive ]]; then
    echo "STOP: $unit is not inactive; no GPU job launched." >&2
    exit 1
  fi
done
attempt="pilot-$(date -u +%Y%m%d-%H%M%S)-$$"
echo "Starting EXCLUSIVE maintenance worker; one fixed 64x64 ROCm task, no auto-reuse."
echo "Attempt: $attempt"
PYTHONPATH=src /opt/comfyui/venv/bin/python -m ai_bridge.gateway.rocm_maintenance_pilot \
  --attempt "$attempt" --execute
echo "Complete. GPU_REUSE_SAFE remains NOT_VERIFIED."
echo "AI services intentionally remain STOPPED pending evidence review."
echo "Evidence: /srv/ai-data/evaluation/rm-rocm-hardware-pilot/$attempt"
