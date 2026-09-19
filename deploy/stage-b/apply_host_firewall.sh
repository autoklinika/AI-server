#!/usr/bin/env bash
set -euo pipefail

echo "===== PRECHECK ====="
echo "SSH_CONNECTION=${SSH_CONNECTION:-unknown}"
systemctl is-active ssh.service || systemctl is-active ssh.socket
systemctl is-active tailscaled.service

# Host policy
sudo ufw default deny incoming
sudo ufw default allow outgoing

# Administracja z LAN 192.168.1.0/24
sudo ufw allow from 192.168.1.0/24 to any port 22 proto tcp comment 'SSH LAN'
sudo ufw allow from 192.168.1.0/24 to any port 9090 proto tcp comment 'Cockpit LAN'

# WVC / domain API z LAN
sudo ufw allow from 192.168.1.0/24 to any port 8080 proto tcp comment 'AI Bridge LAN'

# Administracja przez Tailscale
sudo ufw allow in on tailscale0 to any port 22 proto tcp comment 'SSH Tailscale'
sudo ufw allow in on tailscale0 to any port 9090 proto tcp comment 'Cockpit Tailscale'

# Tailscale transport
sudo ufw allow 41641/udp comment 'Tailscale transport'

sudo ufw --force enable

echo
echo "===== UFW ====="
sudo ufw status verbose

echo
echo "===== LOCAL HEALTH ====="
curl -fsS http://127.0.0.1:11435/health >/dev/null
curl -fsS http://127.0.0.1:8080/health >/dev/null
curl -fsS http://127.0.0.1:8188/system_stats >/dev/null

echo "HOST FIREWALL: PASS"
