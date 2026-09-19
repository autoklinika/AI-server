#!/usr/bin/env bash
set -euo pipefail

sudo ufw disable

echo "===== UFW ====="
sudo ufw status verbose

echo "HOST FIREWALL ROLLBACK: PASS"
