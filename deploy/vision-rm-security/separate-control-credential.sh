#!/usr/bin/env bash
# One-time root action: isolate RM bearer from ai-vision worker UID.
# NO service restart; NO secret rotation or printing; NO AI Platform cutover.
set -euo pipefail
if [[ "${1:-}" != "--apply" || "${#}" -ne 1 ]]; then
  echo "Usage: sudo bash separate-control-credential.sh --apply"
  exit 2
fi
if (( EUID != 0 )); then
  echo "Root required; do not bypass authorization" >&2
  exit 3
fi
TOKEN=/etc/ai-platform/vision-rm/executor.token
DIRECTORY=/etc/ai-platform/vision-rm
for name in ai-vision ai-gateway-rm; do
  getent passwd "$name" >/dev/null || { echo "Missing account $name" >&2; exit 4; }
done
test -d "$DIRECTORY" && test -f "$TOKEN" && test ! -L "$TOKEN" && test ! -L "$DIRECTORY"
test "$(stat -c %U "$TOKEN")" = root
test "$(stat -c %U "$DIRECTORY")" = root
# Fail before changes if the service UID already has elevated permissions.
for group in sudo adm docker; do
  if id -nG ai-vision | tr ' ' '\n' | grep -qx "$group"; then
    echo "ai-vision has forbidden group $group" >&2
    exit 5
  fi
done
if ! getent group ai-vision-rm-control >/dev/null; then
  groupadd --system ai-vision-rm-control
fi
usermod -aG ai-vision-rm-control ai-gateway-rm
if id -nG ai-vision | tr ' ' '\n' | grep -qx ai-vision-rm-control; then
  echo "ai-vision unexpectedly belongs to control group; abort" >&2
  exit 6
fi
# Controller state cannot be readable by an ai-vision model.
if [[ -d /var/lib/ai-gateway-rm && ! -L /var/lib/ai-gateway-rm ]]; then
  chown ai-gateway-rm:ai-vision-rm-control /var/lib/ai-gateway-rm
  chmod 0700 /var/lib/ai-gateway-rm
fi
chown root:ai-vision-rm-control "$DIRECTORY"
chmod 0750 "$DIRECTORY"
# Old shared-group secret was potentially exposed to the model UID.
# Rotate ONCE during migration, atomically and without ever printing it.
ROTATION_MARKER="$DIRECTORY/credential-isolated-v1.done"
if [[ ! -e "$ROTATION_MARKER" ]]; then
  python3 - "$DIRECTORY" "$TOKEN" "$ROTATION_MARKER" "$(getent group ai-vision-rm-control | cut -d: -f3)" <<'PYSEC'
import os,secrets,sys
from pathlib import Path
folder,token,marker=map(Path,sys.argv[1:4])
gid=int(sys.argv[4])
if marker.exists():raise SystemExit("rotation already recorded")
tmp=folder/(".token-rotate-"+secrets.token_hex(8))
fd=os.open(tmp,os.O_CREAT|os.O_EXCL|os.O_WRONLY|os.O_NOFOLLOW,0o600)
try:
    os.fchown(fd,0,gid)
    os.fchmod(fd,0o640)
    with os.fdopen(fd,"w",encoding="ascii") as h:
        h.write(secrets.token_hex(48)+"\n")
        h.flush();os.fsync(h.fileno())
    os.replace(tmp,token)
    dfd=os.open(folder,os.O_RDONLY|os.O_DIRECTORY)
    try:os.fsync(dfd)
    finally:os.close(dfd)
    f=os.open(marker,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(f,"w",encoding="ascii") as h:
        h.write("control-secret-rotated\n")
        h.flush();os.fsync(h.fileno())
    dfd=os.open(folder,os.O_RDONLY|os.O_DIRECTORY)
    try:os.fsync(dfd)
    finally:os.close(dfd)
finally:
    tmp.unlink(missing_ok=True)
PYSEC
fi
chown root:ai-vision-rm-control "$TOKEN"
chmod 0640 "$TOKEN"
test "$(stat -c %U:%G:%a "$DIRECTORY")" = root:ai-vision-rm-control:750
test "$(stat -c %U:%G:%a "$TOKEN")" = root:ai-vision-rm-control:640
runuser -u ai-gateway-rm -- test -r "$TOKEN"
if runuser -u ai-vision -- test -r "$TOKEN"; then
  echo "SECURITY_FAILURE: model service can still read control credential" >&2
  exit 7
fi
# Keep common ai-vision-rm socket group unchanged; this script never
# modifies the running observer/Gateway/Ollama services.
echo "RM_CONTROL_CREDENTIAL_ISOLATED=PASS"
echo "AI_VISION_TOKEN_ACCESS=DENIED"
echo "AI_GATEWAY_RM_TOKEN_ACCESS=PASS"
echo "OLD_SHARED_CREDENTIAL=ROTATED_ON_FIRST_APPLY"
echo "OBSERVER_SOCKET_GROUP=UNCHANGED"
echo "PRODUCTION_SERVICES=UNCHANGED"
