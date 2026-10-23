#!/usr/bin/env bash
# Operator-only, fail-closed recovery review of one failed DEV ComfyUI test.
# No process restart/stop, no GPU compute, no modified production unit.
set -Eeuo pipefail
umask 077
BASE=/srv/ai-data/staging/comfy-ondemand-maintenance-dev-20261023
DEV=ai-rm-comfy-ondemand-dev.service
WATCHDOG=ai-rm-comfy-restore-20261023.timer
MODE=--check
if (( $# )); then MODE="$1"; fi
if [[ "$MODE" != "--check" && "$MODE" != "--repair" ]]; then
    echo "Usage: --check (unprivileged) or sudo --repair"; exit 2
fi
if [[ "$MODE" == "--repair" && "$(id -u)" -ne 0 ]]; then
    echo "REFUSE: root operator authorization required";exit 22
fi
cd "$BASE"
exec 9>"$BASE/.maintenance-global.lock"
flock -n 9 || { echo "REFUSE: concurrent DEV maintenance";exit 11; }
[[ "$(systemctl is-active ai-gateway.service)" == active ]] || exit 12
[[ "$(systemctl is-active comfyui.service)" == active ]] || exit 13
[[ "$(systemctl is-active ollama.service)" == active ]] || exit 14
[[ "$(systemctl is-active ai-egpu-gen3-ha.service)" == active ]] || exit 15
[[ "$(systemctl show -P ActiveState "$DEV")" == inactive ]] || exit 16
[[ "$(systemctl show -P MainPID "$DEV")" == 0 ]] || exit 17
[[ "$(systemctl show -P ActiveState "$WATCHDOG")" == inactive ]] || exit 18
[[ "$(systemctl show -P ActiveState ai-rm-comfy-restore-20261023.service)" != active ]] || exit 19
! ss -lnt | grep -q '127.0.0.1:11657' || exit 20
test -e "$BASE/real-comfy-gpu-result.json"
test -e "$BASE/dev-residency.blocked"
[[ "$(systemctl show -P MainPID comfyui.service)" =~ ^[1-9][0-9]+$ ]] || exit 21
python3 - "$BASE" "$MODE" <<'PY'
import json,sys,re,subprocess
from pathlib import Path
from urllib.request import urlopen
root=Path(sys.argv[1])
p=root/"real-comfy-gpu-result.json"
if sys.argv[2]=="--repair":
    data=json.loads(p.read_text())
    if not (data.get("verdict")=="INCOMPLETE" and
            data.get("scope")=="DEV transient system-manager real ROCm" and
            data.get("gpu_reuse_safe")=="NOT_VERIFIED" and
            data.get("n1_gpu_grants")=="NOT_ADMITTED" and
            data.get("failure_class")=="RuntimeError"):
        raise SystemExit("BLOCKED: failure record is not recognized")
else:
    if not p.is_file() or not (root/"dev-residency.blocked").is_file():
        raise SystemExit("BLOCKED: missing DEV failure evidence")
with urlopen("http://127.0.0.1:11435/health",timeout=4) as f:h=json.load(f)
assert h["status"]=="ok"
assert h["resource_manager"]["state"]=="IDLE"
assert h["gpu_residency"]["recovery_required"] is False
assert h["scheduler"]["active_count"]==h["scheduler"]["queued_count"]==0
with urlopen("http://127.0.0.1:8188/ai-platform/residency",timeout=4) as f:c=json.load(f)
assert c["schema_version"]==1
assert c["queue_running"]==c["queue_pending"]==c["loaded_models"]==0
assert c["cleanup_pending"] is False
with urlopen("http://127.0.0.1:11434/api/ps",timeout=3) as f:
    assert json.load(f)["models"]==[]
v=subprocess.run(["nvidia-smi",
    "--query-gpu=memory.used,pcie.link.gen.current,pcie.link.width.current",
    "--format=csv,noheader,nounits"],capture_output=True,text=True,
    timeout=4,check=True)
used,gen,width=[int(x.strip()) for x in v.stdout.strip().split(",")]
assert used<=256 and (gen,width)==(3,4)
for bdf in ("0000:00:01.1","0000:01:00.0","0000:02:00.0","0000:03:00.0"):
    for tp in ("correctable","nonfatal","fatal"):
        x=Path("/sys/bus/pci/devices")/bdf/("aer_dev_"+tp)
        if x.is_file():
            totals=[s for s in x.read_text().splitlines() if s.startswith("TOTAL_")]
            assert len(totals)==1 and int(totals[0].split()[-1])==0
print("FAILED_ATTEMPT_RECORD_AND_HOST_HEALTH_PASS" if sys.argv[2]=="--repair"
      else "FAILED_ATTEMPT_FILES_PRESENT_HOST_HEALTH_PASS")
PY
if [[ "$MODE" == "--check" ]]; then
    echo "READONLY_DEV_RECOVERY_REVIEW_PASS"
    echo "REPAIR_NOT_EXECUTED: root will repair only input/output/temp/user dirs"
    exit 0
fi
if (( EUID != 0 )); then
    echo "REFUSE: root operator authorization required"; exit 22
fi
# Only this exact verified failure category can authorize archive/reset.
observed="$(journalctl -b -u "$DEV" --since '2026-10-23 23:07:00' \
            --until '2026-10-23 23:10:00' --no-pager -o cat | \
            grep -F 'You do not have read permissions for' | tail -n 1 || true)"
if [[ "$observed" != *"$BASE/user"* ]]; then
    echo "REFUSE: no matching ComfyUI user-directory failure in current-boot journal";exit 31
fi
echo "EXACT_USER_DIRECTORY_DENIAL_IN_SYSTEMD_JOURNAL_PASS"
# Full-privileged check: production ComfyUI must be the ONLY visible AMD
# owner, and the failed DEV transient cgroup must be empty.
p="$(systemctl show -P MainPID comfyui.service)"
cg="/sys/fs/cgroup/system.slice/$DEV"
if [[ -f "$cg/cgroup.procs" && -s "$cg/cgroup.procs" ]]; then
    echo "REFUSE: DEV service cgroup still has processes";exit 23
fi
set +e
owned="$(fuser /dev/kfd /dev/dri/renderD128 2>"$BASE/recovery-fuser-stderr.log")"
owned_rc=$?
set -e
if (( owned_rc != 0 )); then
    echo "REFUSE: AMD device-holder enumeration failed";exit 24
fi
python3 - "$owned" "$p" <<'PY'
import sys
pids=set(sys.argv[1].split())
expected={sys.argv[2]}
if pids!=expected:
    raise SystemExit("REFUSE: foreign or missing AMD device owner")
print("AMD_VISIBLE_OWNER_IS_ORIGINAL_COMFYUI_ONLY")
PY
# Restrict only the four DEV test folders; leave backup/evidence root-owned.
for folder in input output temp user; do
    path="$BASE/$folder"
    if [[ -L "$path" ]]; then
        echo "REFUSE: symlink in DEV directory";exit 25
    fi
    if [[ -e "$path" && ! -d "$path" ]]; then
        echo "REFUSE: non-directory DEV path";exit 26
    fi
    if [[ -d "$path" && -n "$(find "$path" -mindepth 1 -maxdepth 1 -print -quit)" ]]; then
        echo "REFUSE: DEV folder is not empty; preserve previous artifacts";exit 30
    fi
    install -d -o harrypotter -g harrypotter -m 0700 "$path"
    if [[ "$(stat -c %U:%G:%a "$path")" != "harrypotter:harrypotter:700" ]]; then
        echo "REFUSE: directory owner/mode mismatch";exit 27
    fi
    if ! runuser -u harrypotter -- test -r "$path" -a -w "$path" -a -x "$path"; then
        echo "REFUSE: ComfyUI user cannot access DEV directory";exit 28
    fi
done
# Root owns the evidence/recovery marker until it is intentionally archived.
archive="$BASE/failed-20261023-2308"
if [[ -e "$archive" ]]; then
    echo "REFUSE: prior recovery archive exists";exit 29
fi
mkdir -m 0700 "$archive"
python3 - "$BASE" "$archive" <<'PY'
import json,shutil,sys,hashlib
from pathlib import Path
root=Path(sys.argv[1]); archive=Path(sys.argv[2])
for name in ("real-comfy-gpu-result.json","dev-residency.blocked",
             "real-gpu-dev.log","rollback.log","watchdog-setup.log"):
    p=root/name
    if not p.is_file() or p.is_symlink():
        raise SystemExit("REFUSE: evidence file absent/not regular: "+name)
    f=archive/name
    shutil.copyfile(p,f)
    f.chmod(0o600)
    assert hashlib.sha256(p.read_bytes()).digest()==hashlib.sha256(f.read_bytes()).digest()
record=json.loads((archive/"real-comfy-gpu-result.json").read_text())
assert record["verdict"]=="INCOMPLETE" and record["failure_class"]=="RuntimeError"
print("FAILED_DEV_GPU_TEST_EVIDENCE_ARCHIVED_SHA256_PASS")
PY
# Remove the DEV-only failure marker/result from the active staging root
# only after every precondition passed and the original has been archived.
mv "$BASE/real-comfy-gpu-result.json" "$archive/record-moved-original.json"
mv "$BASE/dev-residency.blocked" "$archive/marker-moved-original.txt"
test ! -e "$BASE/real-comfy-gpu-result.json"
test ! -e "$BASE/dev-residency.blocked"
echo "DEV_FAILURE_REVIEW_AND_DIRECTORY_REPAIR_PASS"
echo "NOTE: GPU_REUSE_SAFE=NOT_VERIFIED; this ONLY prepares a separately authorized retry"
