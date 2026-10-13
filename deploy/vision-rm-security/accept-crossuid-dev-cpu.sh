#!/usr/bin/env bash
# Operator-controlled one-shot CPU-only test with real service UIDs and broker.
# No model GPU imports; mocked Ollama/Comfy backend; production untouched.
set -euo pipefail
if [[ "${1:-}" != "--apply" || $# -ne 1 || $EUID -ne 0 ]]; then
  echo "Usage: sudo bash accept-crossuid-dev-cpu.sh --apply" >&2;exit 2
fi
SOURCE=/opt/ai-platform/vision-rm-candidate
DIR=/srv/ai-data/evaluation/vision-rm-service
RESULT="$DIR/crossuid-cpu-result.json"
MARKER=/var/lib/ai-gateway-rm/dev-gpu-test.blocked
SOCKET=/run/ai-vision-rm-broker/control.sock
for unit in ai-vision-rm-dev-gateway ai-vision-rm-broker ai-vision-rm-runner; do
  if systemctl is-active --quiet "$unit"; then
    echo "DEV_UNIT_ALREADY_ACTIVE=$unit" >&2;exit 3
  fi
done
if [[ -e "$RESULT" || -e "$MARKER" || -e "$SOCKET" ]]; then
  echo "STALE_TEST_STATE=YES; refuse overwrite/recovery" >&2;exit 4
fi
test -f "$SOURCE/src/ai_bridge/benchmarks/vision_rm_dev_gateway.py"
test -f /usr/local/libexec/ai-platform/vision-rm-runner.py
test -f /usr/local/libexec/ai-platform/vision-rm-dev-cpu-worker.py
test -f /usr/local/share/ai-platform/vision-rm/job.json
for name in ai-vision-gpu-observer ai-gateway ollama; do systemctl is-active --quiet "$name";done
python3 - <<'PRE'
import json,urllib.request
with urllib.request.urlopen('http://127.0.0.1:11435/status',timeout=5) as r:
    d=json.load(r)
assert d['gpu_residency']['state']=='llm'
assert not d['gpu_residency']['recovery_required']
assert d['resource_leases']['lease_count']==0
assert d['active']==[] and d['queued']==[]
print("PRODUCTION_RM_IDLE=PASS")
PRE
echo "CPU_ONLY_CROSS_UID_TEST=STARTING"
stop_dev() {
  systemctl stop ai-vision-rm-broker.service >/dev/null 2>&1 || true
  systemctl stop ai-vision-rm-dev-gateway.service >/dev/null 2>&1 || true
}
trap stop_dev EXIT
systemctl start ai-vision-rm-dev-gateway.service
/usr/bin/python3 - <<'WAITHTTP'
import json,time,urllib.request
deadline=time.monotonic()+12
while time.monotonic()<deadline:
    try:
        with urllib.request.urlopen('http://127.0.0.1:11575/status',timeout=2) as r:
            state=json.load(r)
        if (state['gpu_residency']['state']=='llm' and
                state['resource_leases']['lease_count']==0 and
                any(p['provider_id']=='vision-local' for p in state['registry']['providers'])):
            print('ISOLATED_DEV_GATEWAY_READY=PASS')
            raise SystemExit(0)
    except (OSError,KeyError,ValueError,TimeoutError):
        pass
    time.sleep(.15)
raise SystemExit('isolated DEV Gateway readiness timeout')
WAITHTTP
systemctl start ai-vision-rm-broker.service
/usr/bin/python3 - <<'WAITBROKER'
from pathlib import Path
import time
deadline=time.monotonic()+12
while time.monotonic()<deadline:
    if Path('/run/ai-vision-rm-broker/control.sock').is_socket():
        print('ISOLATED_BROKER_SOCKET_READY=PASS')
        break
    time.sleep(.1)
else:raise SystemExit('DEV broker socket readiness timeout')
WAITBROKER
# A one-shot service: systemctl returns only after the model-only worker exits.
systemctl start ai-vision-rm-runner.service
test -f "$RESULT"
python3 - "$RESULT" <<'RESULTCHECK'
import json,sys
from pathlib import Path
result=json.loads(Path(sys.argv[1]).read_text())
assert result=={'status':'cpu_only','worker_uid':994,
                'rm_control_credential_absent':True,'gpu_imports':False}
print('MODEL_ONLY_CPU_EXECUTION=PASS')
print('MODEL_CONTROL_CREDENTIAL_LEAK=DENIED')
RESULTCHECK
python3 - <<'CHECK'
import json,urllib.request
with urllib.request.urlopen('http://127.0.0.1:11575/status',timeout=3) as r:
    d=json.load(r)
assert d['gpu_residency']['state']=='llm'
assert not d['gpu_residency']['recovery_required']
assert d['resource_leases']['lease_count']==0
assert d['active']==[] and d['queued']==[]
print('DEV_RM_GPU_RESIDENCY_CLEAN=PASS')
CHECK
test ! -e "$MARKER"
stop_dev
trap - EXIT
systemctl is-active --quiet ai-gateway
systemctl is-active --quiet ollama
test ! -e "$MARKER"
echo "CROSS_UID_CONTROLLER_MODEL_CPU_E2E=PASS"
echo "PRODUCTION_GATEWAY=UNCHANGED"
