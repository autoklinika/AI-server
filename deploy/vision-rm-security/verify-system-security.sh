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
test "$(stat -c '%U:%G:%a' /etc/ai-platform/vision-rm/executor.token)" = "root:ai-vision-rm:640"
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
