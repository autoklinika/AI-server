#!/usr/bin/env bash
# OPERATOR-ONLY DEV negative test. No permanent installs/enable/restarts.
set -Eeuo pipefail
[[ "$(id -u)" == "0" ]] || { echo "Run explicitly with sudo, operator only"; exit 2; }
REPO=/srv/ai-data/staging/gpu-dual-route-20261023/AI-server-dev
TEST="$REPO/deploy/physical-ollama-routing-dev/os_gpu_access_probe.py"
OUT=/srv/ai-data/staging/gpu-dual-route-20261023
[[ -f "$TEST" ]] || exit 2
[[ "$(systemctl is-active ai-egpu-gen3-ha.service)" == "active" ]] || exit 2
[[ "$(systemctl is-active ai-gateway.service)" == "active" ]] || exit 2
[[ "$(systemctl is-active ollama.service)" == "active" ]] || exit 2

# No GPU model or RM job may run concurrently with this permission-only test.
python3 -B - <<'PY'
import json,urllib.request,subprocess
with urllib.request.urlopen("http://127.0.0.1:11435/health",timeout=3) as f:
    data=json.load(f)
assert data["resource_manager"]["state"]=="IDLE"
assert data["gpu_residency"]["recovery_required"] is False
assert data["scheduler"]["active_count"]==data["scheduler"]["queued_count"]==0
with urllib.request.urlopen("http://127.0.0.1:11434/api/ps",timeout=3) as f:
    assert not json.load(f)["models"]
gpu=subprocess.run(["nvidia-smi","--query-gpu=memory.used,pcie.link.gen.current,pcie.link.width.current",
                    "--format=csv,noheader,nounits"],check=True,capture_output=True,text=True,timeout=3)
used,gen,width=map(int,gpu.stdout.strip().split(","))
assert used<=256 and gen==3 and width==4
print("SYSTEM_DEV_PREFLIGHT_PASS")
PY

run_case() {
    local tag="$1" permitted="$2" outfile="$3"
    echo "SYSTEM_DEVICE_POLICY_START=$tag"
    local -a allow_props=(--property="DeviceAllow=$permitted rw")
    if [[ "$tag" == "rtx" ]]; then
        allow_props+=(--property="DeviceAllow=/dev/nvidiactl rw")
    fi
    # The system manager creates one transient service as a nonroot user.
    # A user manager DevicePolicy did not enforce GPU isolation in prior probe.
    # This does not prove a global denial for other host principals.
    systemd-run --system --pipe --wait --collect \
       --unit="ai-rm-dev-$tag-probe-20261023" \
       --uid=harrypotter \
       --property=Restart=no \
       --property=RuntimeMaxSec=15s \
       --property=KillMode=control-group \
       --property=DevicePolicy=closed \
       "${allow_props[@]}" \
       --property=MemoryMax=96M \
       --property=MemorySwapMax=0 \
       --property=TasksMax=16 \
       --property=NoNewPrivileges=yes \
       /usr/bin/python3 -I -B "$TEST" "$tag" 2>&1 | tee "$outfile"
    grep -q "SYSTEM_SCOPE_DEVICE_BOUNDARY_PASS $tag" "$outfile"
}
run_case amd /dev/dri/renderD128 "$OUT/system-scope-negative-amd.log"
run_case rtx /dev/nvidia0 "$OUT/system-scope-negative-rtx.log"
echo "SYSTEM_SCOPE_FIXED_GPU_DEVICE_ALLOW_DENY_PASS"
echo "GLOBAL_HOST_GPU_EXCLUSIVITY=NOT_VERIFIED"
echo "DRIVER_REUSE_SAFE=NOT_VERIFIED"
echo "N1_GPU_GRANTS=NOT_ADMITTED"
