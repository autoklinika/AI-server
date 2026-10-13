#!/usr/bin/env bash
# Administrator-run installation: no AI Gateway restart or deployment.
set -euo pipefail
if [[ "${1:-}" != "--apply" || "${#}" -ne 1 ]]; then
  echo "Usage: sudo bash install-system-security.sh --apply"
  exit 2
fi
if (( EUID != 0 )); then
  echo "ERROR: requires root; no automatic privilege escalation" >&2
  exit 3
fi
SELF_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
SRC="$SELF_DIR/vision_gpu_observer.py"
UNIT="$SELF_DIR/ai-vision-gpu-observer.service"
test -f "$SRC" && test -f "$UNIT" || { echo "ERROR: missing packaged files" >&2; exit 4; }
for name in python3 useradd groupadd usermod systemctl loginctl install stat; do
  command -v "$name" >/dev/null || { echo "ERROR: missing $name" >&2; exit 5; }
done
test -c /dev/kfd || { echo "ERROR: missing AMD KFD" >&2; exit 6; }
test -c /dev/dri/renderD128 || { echo "ERROR: missing renderD128" >&2; exit 7; }
python3 -m py_compile "$SRC"
bash -n "$SELF_DIR/install-system-security.sh"
umask 0077

# Creates only new isolated identities. Existing accounts never gain sudo.
if ! getent group ai-vision-rm >/dev/null; then
  groupadd --system ai-vision-rm
fi
# Separate control-plane credential access from observer/socket permissions.
if ! getent group ai-vision-rm-control >/dev/null; then
  groupadd --system ai-vision-rm-control
fi
if ! getent passwd ai-vision >/dev/null; then
  useradd --system --create-home --home-dir /var/lib/ai-vision \
    --shell /usr/sbin/nologin --gid ai-vision-rm --groups render,video ai-vision
fi
if ! getent passwd ai-gateway-rm >/dev/null; then
  useradd --system --create-home --home-dir /var/lib/ai-gateway-rm \
    --shell /usr/sbin/nologin --gid ai-vision-rm ai-gateway-rm
fi
for account in ai-vision ai-gateway-rm; do
  test "$(id -u "$account")" -ne 0
  test "$(id -gn "$account")" = ai-vision-rm
done
usermod -aG render,video ai-vision
usermod -aG ai-vision-rm-control ai-gateway-rm
if id -nG ai-vision | tr ' ' '\n' | grep -qx ai-vision-rm-control; then
  echo "ERROR: ai-vision cannot belong to control credential group" >&2
  exit 7
fi

install -d -o root -g ai-vision-rm-control -m 0750 /etc/ai-platform/vision-rm
TOKEN=/etc/ai-platform/vision-rm/executor.token
if [[ -L "$TOKEN" ]]; then
  echo "ERROR: credential path is symbolic link" >&2
  exit 8
fi
if [[ ! -e "$TOKEN" ]]; then
  # Never overwrite existing credential during idempotent installation.
  python3 -c 'import secrets; print(secrets.token_hex(48))' > "$TOKEN"
fi
test -f "$TOKEN" || { echo "ERROR: credential must be regular file" >&2; exit 9; }
chown root:ai-vision-rm-control "$TOKEN"
chmod 0640 "$TOKEN"
test "$(stat -c %a "$TOKEN")" = 640

install -d -o ai-vision -g ai-vision-rm -m 0750 /var/lib/ai-vision
install -d -o ai-gateway-rm -g ai-vision-rm-control -m 0700 /var/lib/ai-gateway-rm
install -d -o ai-vision -g ai-vision-rm -m 0750 /srv/ai-data/evaluation/vision-rm-service
install -d -o root -g root -m 0755 /usr/local/libexec/ai-platform
install -o root -g root -m 0755 "$SRC" /usr/local/libexec/ai-platform/vision-gpu-observer.py
install -o root -g root -m 0644 "$UNIT" /etc/systemd/system/ai-vision-gpu-observer.service

# Persistent service-user manager is needed for systemd-run --user --scope.
loginctl enable-linger ai-vision
systemctl daemon-reload
systemctl enable --now ai-vision-gpu-observer.service
systemctl is-active --quiet ai-vision-gpu-observer.service
SOCK=/run/ai-vision-gpu-observer/observer.sock
test -S "$SOCK"
test "$(stat -c %a "$SOCK")" = 660
test "$(stat -c %U "$SOCK")" = root
test "$(stat -c %G "$SOCK")" = ai-vision-rm

echo "SYSTEM_SECURITY_INSTALL=PASS"
echo "VISION_SERVICE_UID=$(id -u ai-vision)"
echo "GATEWAY_STAGED_UID=$(id -u ai-gateway-rm)"
echo "GPU_OBSERVER=active"
echo "CREDENTIAL=protected_not_displayed"
echo "PRODUCTION_GATEWAY=unchanged"
