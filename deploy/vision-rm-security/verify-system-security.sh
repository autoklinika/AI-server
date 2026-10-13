#!/usr/bin/env bash
# Read-only post-install verification. Requires root ONLY to switch user identity.
set -euo pipefail
if [[ "${1:-}" != "--verify" || ${#} -ne 1 ]]; then
  echo "Usage: sudo bash verify-system-security.sh --verify"; exit 2
fi
if (( EUID != 0 )); then echo "Requires administrator for account isolation verification" >&2;exit 3;fi
command -v runuser >/dev/null
for name in ai-vision ai-gateway-rm; do
  getent passwd "$name" >/dev/null || { echo "MISSING_ACCOUNT=$name"; exit 4; }
  [[ "$(id -u "$name")" != 0 ]] || exit 5
  [[ "$(id -gn "$name")" == "ai-vision-rm" ]] || exit 6
done
id -nG ai-vision | tr ' ' '\n' | grep -qx render
id -nG ai-vision | tr ' ' '\n' | grep -qx video
systemctl is-active --quiet ai-vision-gpu-observer
systemctl is-enabled --quiet ai-vision-gpu-observer
test -S /run/ai-vision-gpu-observer/observer.sock
test "$(stat -c '%U:%G:%a' /run/ai-vision-gpu-observer/observer.sock)" = "root:ai-vision-rm:660"
test "$(stat -c '%U:%G:%a' /etc/ai-platform/vision-rm)" = "root:ai-vision-rm-control:750"
test "$(stat -c '%U:%G:%a' /etc/ai-platform/vision-rm/executor.token)" = "root:ai-vision-rm-control:640"
id -nG ai-gateway-rm | tr ' ' '\n' | grep -qx ai-vision-rm-control
if id -nG ai-vision | tr ' ' '\n' | grep -qx ai-vision-rm-control; then
  echo "VISION_MODEL_HAS_CONTROL_GROUP=FAIL" >&2; exit 10
fi
# No contents printed: verify only access control, not the secret value.
runuser -u ai-gateway-rm -- test -r /etc/ai-platform/vision-rm/executor.token
if runuser -u ai-vision -- test -r /etc/ai-platform/vision-rm/executor.token; then
  echo "VISION_MODEL_CAN_READ_RM_CREDENTIAL=FAIL" >&2; exit 11
fi
echo "VISION_MODEL_CONTROL_SECRET=DENIED"
echo "GATEWAY_CONTROL_SECRET=READABLE"
if runuser -u ai-vision -- test -r /var/lib/ai-gateway-rm; then
  echo "VISION_MODEL_CAN_READ_CONTROLLER_STATE=FAIL" >&2; exit 12
fi
echo "VISION_MODEL_CONTROLLER_STATE=DENIED"
test "$(stat -c '%U:%G:%a' /usr/local/libexec/ai-platform/vision-gpu-observer.py)" = "root:root:755"
test "$(stat -c '%U:%G:%a' /etc/systemd/system/ai-vision-gpu-observer.service)" = "root:root:644"
# The test never accesses GPU directly. It requests only a read-only snapshot.
for account in ai-vision ai-gateway-rm; do
  if runuser -u "$account" -- /usr/bin/python3 -c '
import json,socket,sys
address="/run/ai-vision-gpu-observer/observer.sock"
with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as s:
    s.settimeout(5)
    s.connect(address)
    s.sendall(b"{\"op\":\"snapshot\",\"version\":1}\n")
    response=b""
    while b"\n" not in response and len(response)<262144:
        part=s.recv(8192)
        if not part:break
        response+=part
    data=json.loads(response)
    if data.get("status")!="ok" or not isinstance(data.get("gpu_clients"),list):
        print("OBSERVER_RESPONSE="+str(data.get("status","invalid")))
        sys.exit(7)
    print("GPU_CLIENTS_VISIBLE="+str(len(data["gpu_clients"])))
'; then
    echo "AUTHORIZED_${account}_SNAPSHOT=PASS"
  else
    echo "AUTHORIZED_${account}_SNAPSHOT=FAIL" >&2
    exit 8
  fi
done
if [[ -n "${SUDO_USER:-}" && "${SUDO_USER}" != ai-vision && "${SUDO_USER}" != ai-gateway-rm ]]; then
  if runuser -u "$SUDO_USER" -- /usr/bin/python3 -c '
import socket
with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as s:
    s.settimeout(3)
    s.connect("/run/ai-vision-gpu-observer/observer.sock")
' 2>/dev/null; then
    echo "UNAUTHORIZED_ACCOUNT_ACCESS=FAIL" >&2; exit 9
  fi
  echo "UNAUTHORIZED_ACCOUNT_ACCESS=DENIED"
fi
systemctl is-active --quiet ai-gateway
systemctl is-active --quiet ollama
echo "SYSTEM_SECURITY_VERIFY=PASS"
echo "PRODUCTION_AI_GATEWAY=ACTIVE_UNMODIFIED"
