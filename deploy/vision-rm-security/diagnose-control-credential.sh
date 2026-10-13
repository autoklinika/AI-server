#!/usr/bin/env bash
# Read-only root diagnostics: never print token, never alter permissions.
set -u
TOKEN=/etc/ai-platform/vision-rm/executor.token
if (( EUID != 0 )); then
  echo "DIAG=NEEDS_ROOT"
  exit 2
fi
echo "DIAG_PHASE=ROOT_PATH"
for path in /etc /etc/ai-platform /etc/ai-platform/vision-rm "$TOKEN"; do
  if [[ -e "$path" ]]; then
    stat -Lc 'PATH=%n OWNER=%U GROUP=%G PERM=%a TYPE=%F' "$path"
  else
    echo "PATH_MISSING=$path"
  fi
done
if [[ -e /etc/ai-platform/vision-rm/credential-isolated-v1.done ]]; then
  echo "ROTATION_MARKER=EXISTS"
else
  echo "ROTATION_MARKER=MISSING"
fi
echo "DIAG_PHASE=GROUP"
getent group ai-vision-rm-control || true
id ai-gateway-rm || true
id ai-vision || true
echo "DIAG_PHASE=SERVICE_USER"
runuser -u ai-gateway-rm -- /usr/bin/id || echo "RUNUSER_ID=FAILED"
runuser -u ai-gateway-rm -- /usr/bin/python3 -c '
import os,pathlib
p=pathlib.Path("/etc/ai-platform/vision-rm/executor.token")
print("WORKER_UID=",os.getuid(),"GROUPS=",os.getgroups())
print("FILE_EXISTS=",p.exists())
print("TOKEN_ACCESS_EFFECTIVE=",os.access(p,os.R_OK,effective_ids=True))
try:
    with p.open("rb") as f:
        f.read(1)
except OSError as e:
    print("TOKEN_OPEN_STATUS=DENIED","ERRNO=",e.errno,"TYPE=",type(e).__name__)
else:
    print("TOKEN_OPEN_STATUS=PASS")
' || echo "RUNUSER_PYTHON=FAILED"
echo "DIAG_PHASE=END"
