#!/usr/bin/env bash
# Install ROOT-OWNED source and disabled DEV-only units. No services STARTED.
# --verify is read-only and intentionally does not require sudo.
set -euo pipefail
if (( $# != 1 )) || [[ "$1" != "--stage" && "$1" != "--verify" ]]; then
  echo "Usage: sudo bash stage-crossuid-dev.sh --stage | bash stage-crossuid-dev.sh --verify"; exit 2
fi
HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if [[ "$1" == "--verify" ]]; then
  exec python3 "$HERE/verify-crossuid-dev-stage.py"
fi
if (( EUID != 0 )); then echo "Administrator approval required" >&2; exit 3; fi
REPO="$(cd -- "$HERE/../.." && pwd)"
SRC="$REPO/src/ai_bridge"
DEST=/opt/ai-platform/vision-rm-candidate
BIN=/usr/local/libexec/ai-platform
MANIFEST=/usr/local/share/ai-platform/vision-rm/job.json
for name in ai-vision ai-gateway-rm; do getent passwd "$name" >/dev/null;done
for name in ai-gateway ollama ai-vision-gpu-observer; do systemctl is-active --quiet "$name"; done
# An interrupted previous installation is not a reason to overwrite root files.
# Attest an existing full stage byte-for-byte; reject partial or divergent state.
stage_paths=(
  "$DEST"
  "$BIN/vision-worker-gate.py"
  "$BIN/vision-rm-runner.py"
  "$BIN/vision-rm-dev-cpu-worker.py"
  "$MANIFEST"
)
for service in ai-vision-rm-dev-gateway ai-vision-rm-broker ai-vision-rm-runner; do
  stage_paths+=("/etc/systemd/system/${service}.service")
done
stage_present=0
for path in "${stage_paths[@]}"; do
  if [[ -e "$path" || -L "$path" ]]; then
    (( stage_present += 1 ))
  fi
done
if (( stage_present != 0 )); then
  if python3 "$HERE/verify-crossuid-dev-stage.py"; then
    echo "DEV_STAGING_EXISTING=VERIFIED_NO_CHANGES"
    echo "CROSS_UID_DEV_STAGING=PASS"
    echo "PRODUCTION_GATEWAY=UNCHANGED"
    exit 0
  fi
  echo "DEV_STAGING_INCOMPLETE_OR_DIVERGENT=BLOCKED; no overwrite attempted" >&2
  exit 4
fi
test -f "$HERE/vision_rm_runner.py"
test -f "$HERE/vision_rm_dev_cpu_worker.py"
test -f "$HERE/vision_rm_dev_cpu_job.json"
test -f "$SRC/benchmarks/vision_rm_dev_gateway.py"
test -f "$SRC/benchmarks/vision_rm_broker.py"
test -f "$SRC/benchmarks/vision_worker_gate.py"
python3 -m py_compile "$HERE/vision_rm_runner.py" "$HERE/vision_rm_dev_cpu_worker.py" "$SRC/benchmarks/vision_rm_dev_gateway.py"
for unit in ai-vision-rm-dev-gateway ai-vision-rm-broker ai-vision-rm-runner; do
  test -f "$HERE/${unit}.service"
done
python3 - "$HERE/vision_rm_dev_cpu_job.json" <<'PYCHECK'
import json,sys
from pathlib import Path
manifest=json.loads(Path(sys.argv[1]).read_text())
assert set(manifest)=={'python','script','args','max_seconds'}
assert manifest['python']=='/usr/bin/python3'
assert manifest['script']=='/usr/local/libexec/ai-platform/vision-rm-dev-cpu-worker.py'
assert manifest['args']==[] and manifest['max_seconds']==25
PYCHECK
test ! -e /srv/ai-data/evaluation/vision-rm-service/crossuid-cpu-result.json
test ! -e /var/lib/ai-gateway-rm/dev-gpu-test.blocked
# Existing production Gateway and root observer never touched.
umask 0022
TEMP="$(mktemp -d /opt/ai-platform/.vision-rm-dev.XXXXXXXX)"
trap 'if [[ -d "${TEMP:-/nonexistent}" ]]; then rm -rf -- "$TEMP"; fi' EXIT
install -d -o root -g root -m 0755 "$TEMP/src"
cp -a "$SRC" "$TEMP/src/ai_bridge"
find "$TEMP" -type d -name __pycache__ -prune -exec rm -rf -- {} +
find "$TEMP" -type f -name '*.pyc' -delete
chown -R root:root "$TEMP"
chmod -R go-w "$TEMP"
chmod -R a+rX "$TEMP"
mv -- "$TEMP" "$DEST"
TEMP=
install -d -o root -g root -m 0755 "$BIN"
install -d -o root -g root -m 0755 /usr/local/share/ai-platform/vision-rm
install -o root -g root -m 0755 "$SRC/benchmarks/vision_worker_gate.py" "$BIN/vision-worker-gate.py"
install -o root -g root -m 0755 "$HERE/vision_rm_runner.py" "$BIN/vision-rm-runner.py"
install -o root -g root -m 0755 "$HERE/vision_rm_dev_cpu_worker.py" "$BIN/vision-rm-dev-cpu-worker.py"
install -o root -g root -m 0644 "$HERE/vision_rm_dev_cpu_job.json" "$MANIFEST"
for unit in ai-vision-rm-dev-gateway ai-vision-rm-broker ai-vision-rm-runner; do
  install -o root -g root -m 0644 "$HERE/${unit}.service" "/etc/systemd/system/${unit}.service"
done
systemctl daemon-reload
# 'systemctl is-enabled --quiet' exits 0 for STATIC units as well as enabled.
# Explicit UnitFileState, service inactivity, symlinks and hashes are attested.
python3 "$HERE/verify-crossuid-dev-stage.py"
echo "DEV_STAGING_EXISTING=NEWLY_INSTALLED"
echo "CROSS_UID_DEV_STAGING=PASS"
echo "DEV_SERVICE_UNITS=INSTALLED_BUT_STOPPED"
echo "DEV_CPU_JOB=ROOT_OWNED_PINNED"
echo "NO_REAL_GPU_MODEL=YES"
echo "PRODUCTION_GATEWAY=UNCHANGED"
