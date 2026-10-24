#!/usr/bin/env bash
# Exact one-shot fault acceptance archive; operator must authorize --archive.
# No GPU work. No production service change. Refuse unknown/partial recovery.
set -Eeuo pipefail
umask 077
BASE=/srv/ai-data/staging/comfy-ondemand-faults-dev-20261024
UNIT=ai-rm-comfy-ondemand-dev.service
TIMER=ai-rm-comfy-faultrestore-20261024.timer
ARCHIVE="$BASE/accepted-stop-fault-20261024-0752"
MODE=--check
if (( $# )); then MODE="$1"; fi
if [[ "$MODE" != "--check" && "$MODE" != "--archive" ]]; then
    echo "Usage: --check | sudo --archive";exit 2
fi
if [[ "$MODE" == "--archive" && "$(id -u)" -ne 0 ]]; then
    echo "REFUSE_UNPRIVILEGED_DEV_RECOVERY";exit 22
fi
cd "$BASE"
exec 9>/srv/ai-data/staging/comfy-ondemand-maintenance-dev-20261023/.maintenance-global.lock
flock -n 9 || { echo "BLOCKED_GPU_MAINTENANCE_LOCK";exit 10; }
for svc in ai-gateway.service comfyui.service ollama.service ai-egpu-gen3-ha.service; do
    test "$(systemctl is-active "$svc")" == active || {
        echo "BLOCKED_PRODUCTION_SERVICE=$svc";exit 11;
    }
done
test "$(systemctl show -P ActiveState "$UNIT")" == inactive
test "$(systemctl show -P MainPID "$UNIT")" == 0
test "$(systemctl show -P ActiveState "$TIMER")" == inactive
test ! -e "$ARCHIVE"
! ss -lnt | grep -q '127.0.0.1:11657'
for src in real-comfy-gpu-result.json real-gpu-dev.log rollback.log \
           dev-residency.blocked watchdog-setup.log; do
    test -f "$BASE/$src"
    test ! -L "$BASE/$src"
done
python3 - "$BASE" <<'PY'
import json,sys,subprocess,re
from pathlib import Path
from urllib.request import urlopen
folder=Path(sys.argv[1])
with urlopen("http://127.0.0.1:11435/health",timeout=5) as r:h=json.load(r)
assert h.get("status")=="ok"
assert h["resource_manager"]["state"]=="IDLE"
assert h["gpu_residency"]["recovery_required"] is False
assert h["scheduler"]["active_count"]==h["scheduler"]["queued_count"]==0
with urlopen("http://127.0.0.1:8188/ai-platform/residency",timeout=4) as r:c=json.load(r)
assert c["schema_version"]==1
assert (c["loaded_models"],c["queue_running"],c["queue_pending"],
        c["cleanup_pending"])==(0,0,0,False)
with urlopen("http://127.0.0.1:11434/api/ps",timeout=4) as r:
    assert json.load(r).get("models")==[]
assert (folder/"dev-residency.blocked").is_file()
assert not (Path("/sys/fs/cgroup/system.slice/ai-rm-comfy-ondemand-dev.service")/"cgroup.procs").exists() or not (Path("/sys/fs/cgroup/system.slice/ai-rm-comfy-ondemand-dev.service")/"cgroup.procs").read_text().strip()
gpu=subprocess.run(["/usr/bin/nvidia-smi",
    "--query-gpu=memory.used,pcie.link.gen.current,pcie.link.width.current",
    "--format=csv,noheader,nounits"],check=True,capture_output=True,text=True,timeout=5)
a=list(map(int,gpu.stdout.strip().split(",")))
assert a[0]<=256 and a[1:]==[3,4]
for bdf in ("0000:00:01.1","0000:01:00.0","0000:02:00.0","0000:03:00.0"):
 for typ in ("correctable","nonfatal","fatal"):
    p=Path(f"/sys/bus/pci/devices/{bdf}/aer_dev_{typ}")
    if p.is_file():
        totals=[s for s in p.read_text().splitlines() if s.startswith("TOTAL_")]
        assert len(totals)==1 and int(totals[0].split()[-1])==0
print("DEV_STOP_FAULT_READONLY_HOST_AUDIT_PASS")
PY
if [[ "$MODE" == "--check" ]]; then
    echo "DEV_STOP_FAULT_ARCHIVE_READONLY_PREFLIGHT_PASS"
    echo "EVIDENCE_AND_RECOVERY_MARKER_UNCHANGED"
    exit 0
fi
test "$(id -u)" == 0
# Accept only the operator-reported injected event; never generic failed jobs.
python3 - "$BASE" <<'PY'
import json,sys
from pathlib import Path
root=Path(sys.argv[1])
out=json.loads((root/"real-comfy-gpu-result.json").read_text())
assert out["verdict"]=="INCOMPLETE"
assert out["scope"]=="DEV transient system-manager real ROCm"
assert out["failure_class"]=="RuntimeError"
assert isinstance(out["image"],dict)
assert out["image"]["width"]==out["image"]["height"]==64
assert out["recovery_marker_left"] is True
assert out["gpu_reuse_safe"]=="NOT_VERIFIED"
assert out["n1_gpu_grants"]=="NOT_ADMITTED"
log=(root/"real-gpu-dev.log").read_text()
assert "GPU_DEV_COMFY_REAL_IMAGE_PASS" in log
assert "DEV_INJECTED_STOP_REFUSAL_AFTER_REAL_VAE" in log
assert "DEV_EXPECTED_STOP_FAULT_RM_FENCED_PASS" in log
rollback=(root/"rollback.log").read_text()
assert "ROLLBACK_COMPLETE" in rollback
print("EXACT_INJECTED_RM_STOP_FAILURE_RECOGNIZED_PASS")
PY
# Full root-visible GPU-holder check, not available in read-only mode.
set +e
holders="$(fuser /dev/kfd /dev/dri/renderD128 2>"$BASE/archive-fuser-stderr.log")"
rc=$?
set -e
test "$rc" -eq 0 || { echo "UNKNOWN_AMD_DEVICE_HOLDER_RESULT";exit 31; }
nowpid="$(systemctl show -P MainPID comfyui.service)"
python3 - "$holders" "$nowpid" <<'PY'
import sys
if set(sys.argv[1].split())!={sys.argv[2]}:
    raise SystemExit("FOREIGN_OR_MISSING_AMD_DEVICE_HOLDER_BLOCKED")
print("ONLY_RESTORED_COMFY_OWNS_AMD_GPU_PASS")
PY
mkdir -m 0700 "$ARCHIVE"
python3 - "$BASE" "$ARCHIVE" <<'PY'
import hashlib,shutil,sys
from pathlib import Path
root,archive=map(Path,sys.argv[1:])
for name in ("real-comfy-gpu-result.json","real-gpu-dev.log",
             "dev-residency.blocked","rollback.log","watchdog-setup.log"):
    original=root/name
    assert original.is_file() and not original.is_symlink()
    dest=archive/name
    shutil.copyfile(original,dest)
    dest.chmod(0o600)
    assert hashlib.sha256(original.read_bytes()).digest()==hashlib.sha256(dest.read_bytes()).digest()
print("NEGATIVE_GPU_FAULT_EVIDENCE_COPIED_SHA256_PASS")
PY
# Only the DEV-owned original marker/result may move into accepted archive.
mv "$BASE/real-comfy-gpu-result.json" "$ARCHIVE/active-original-result.json"
mv "$BASE/dev-residency.blocked" "$ARCHIVE/active-original-marker.txt"
test ! -e "$BASE/real-comfy-gpu-result.json"
test ! -e "$BASE/dev-residency.blocked"
echo "DEV_STOP_FAULT_ARCHIVED_AND_RECOVERY_FENCE_CLEARED_FOR_FUTURE_TEST_PASS"
echo "GPU_REUSE_SAFE=NOT_VERIFIED N1_GPU_GRANTS=NOT_ADMITTED"
