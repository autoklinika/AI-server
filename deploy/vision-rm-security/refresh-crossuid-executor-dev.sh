#!/usr/bin/env bash
# One-shot, pinned DEV hotfix staging plus CPU-only acceptance. Never production.
set -euo pipefail
if [[ "${1:-}" != "--apply-and-test" || $# -ne 1 || $EUID -ne 0 ]]; then
  echo "Usage: sudo bash refresh-crossuid-executor-dev.sh --apply-and-test" >&2
  exit 2
fi
HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd -- "$HERE/../.." && pwd)"
REL=benchmarks/vision_rm_executor.py
SOURCE="$REPO/src/ai_bridge/$REL"
TARGET="/opt/ai-platform/vision-rm-candidate/src/ai_bridge/$REL"
OLD_SHA=9df867af596bf72460572d766a8e67d00f22b9c6a9030ca29a0b0ad6c6f72e21
NEW_SHA=fdb810e06b1e61c62bec54791cfe4cdfa8e0b4eec11baa5bdbf512c7478a1418

# No overwriting a changed target, accidental source revision, or active DEV task.
[[ "$(sha256sum "$SOURCE" | cut -d' ' -f1)" == "$NEW_SHA" ]] || {
  echo "DEV_HOTFIX_SOURCE_HASH=DENIED" >&2; exit 3;
}
[[ "$(sha256sum "$TARGET" | cut -d' ' -f1)" == "$OLD_SHA" ]] || {
  echo "DEV_HOTFIX_TARGET_HASH=DENIED" >&2; exit 4;
}
for unit in ai-vision-rm-dev-gateway ai-vision-rm-broker ai-vision-rm-runner; do
  state="$(systemctl show "$unit.service" -p ActiveState --value)"
  [[ "$state" == inactive || "$state" == failed ]] || {
    echo "DEV_HOTFIX_ACTIVE_UNIT=DENIED:$unit:$state" >&2; exit 5;
  }
done
if ps -eo uid=,args= | awk '$1==994 && (/vision-worker-gate[.]py/ || /vision-rm-dev-cpu-worker[.]py/ || /vision-rm-runner[.]py/) {found=1} END {exit !found}'; then
  echo "DEV_HOTFIX_RUNNING_MODEL_PROCESS=DENIED" >&2
  exit 6
fi
[[ ! -e /srv/ai-data/evaluation/vision-rm-service/crossuid-cpu-result.json ]] || {
  echo "DEV_RESULT_ALREADY_EXISTS=DENIED" >&2; exit 7;
}
[[ ! -e /var/lib/ai-gateway-rm/dev-gpu-test.blocked ]] || {
  echo "DEV_GPU_BLOCK_MARKER_PRESENT=DENIED" >&2; exit 8;
}
[[ ! -e /run/ai-vision-rm-broker/control.sock ]] || {
  echo "DEV_BROKER_SOCKET_PRESENT=DENIED" >&2; exit 9;
}

# Verify the ENTIRE previous root-owned stage is immutable and matches the
# source tree except this one exact, hash-pinned approved code change.
python3 - "$HERE" "$SOURCE" "$TARGET" "$OLD_SHA" "$NEW_SHA" <<'PY'
import hashlib,importlib.util,sys
from pathlib import Path
here,source,target,old_sha,new_sha=sys.argv[1:]
spec=importlib.util.spec_from_file_location("staging",Path(here)/"verify-crossuid-dev-stage.py")
v=importlib.util.module_from_spec(spec)
spec.loader.exec_module(v)
source,target=Path(source),Path(target)
assert source.resolve()==v.SRC/"benchmarks/vision_rm_executor.py"
assert target.resolve()==v.DEST/"src/ai_bridge/benchmarks/vision_rm_executor.py"
assert v.sha256(source).hex()==new_sha and v.sha256(target).hex()==old_sha
original_hash=v.sha256
def old_stage_hash(p):
    return bytes.fromhex(old_sha) if Path(p)==source else original_hash(p)
original_properties=v.systemd_properties
def stopped_service(service):
    state=original_properties(service)
    if service=="ai-vision-rm-runner" and state["ActiveState"]=="failed" and state["SubState"]=="failed":
        return {**state,"ActiveState":"inactive","SubState":"dead"}
    return state
v.sha256=old_stage_hash
v.systemd_properties=stopped_service
v.verify()
print("DEV_PREVIOUS_ROOT_STAGE_EXCEPT_PINNED_FILE=PASS")
PY

temp="$(mktemp "${TARGET}.hotfix.XXXXXXXX")"
trap 'rm -f -- "${temp:-/nonexistent}"' EXIT
install -o root -g root -m 0644 "$SOURCE" "$temp"
[[ "$(sha256sum "$temp" | cut -d' ' -f1)" == "$NEW_SHA" ]] || {
  echo "DEV_HOTFIX_COPY_HASH=DENIED" >&2; exit 10;
}
mv -f -- "$temp" "$TARGET"
temp=
# Clear only systemd's failed bookkeeping, no service starts or restarts.
systemctl reset-failed ai-vision-rm-runner.service
python3 "$HERE/verify-crossuid-dev-stage.py"
echo "DEV_HOTFIX_PINNED_STAGE=PASS"
echo "PRODUCTION_SERVICES_RESTARTED=NO"
echo "CPU_ONLY_CROSS_UID_RETRY=STARTING"
exec bash "$HERE/accept-crossuid-dev-cpu.sh" --apply
