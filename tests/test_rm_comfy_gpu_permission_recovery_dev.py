"""Safety regression: failed DEV test directory ownership, archived recovery, no prod writes."""
import ast
from pathlib import Path
import subprocess

ROOT=Path(__file__).resolve().parents[1]
D=ROOT/"deploy/comfy-ondemand-dev/maintenance-20261023"


def read(name):
    return (D/name).read_text()


def test_all_operator_scripts_syntax_and_python_ast():
    for f in ("run-maintenance-dev.sh","recover-after-failure-dev.sh",
              "rollback.sh"):
        x=subprocess.run(["bash","-n",str(D/f)],capture_output=True,
                         text=True,timeout=4)
        assert x.returncode==0,(f,x.stderr)
    ast.parse(read("real_comfy_gpu_rm_harness.py"))


def test_directory_access_checked_before_service_outage():
    s=read("run-maintenance-dev.sh")
    for item in (
        "for folder in input output temp user; do",
        "DEV_DIRECTORY_OWNER_MODE_INVALID",
        "DEV_COMFY_USER_DIRECTORY_ACCESS_DENIED",
        "DEV_COMFY_UID_DIRECTORY_RW_PASS",
        'stat -c %U:%G:%a "$work"',
        'runuser -u harrypotter -- test -r "$work"',
    ):
        assert item in s
    pos=s.index("DEV_COMFY_UID_DIRECTORY_RW_PASS")
    assert pos<s.index("ROLLBACK_WATCHDOG_ARMING")
    assert pos<s.index("systemctl stop ai-gateway.service")
    assert "install -d -o harrypotter" not in s
    assert "chown " not in s


def test_repair_is_root_only_and_does_not_mutate_production_services():
    r=read("recover-after-failure-dev.sh")
    assert 'if [[ "$MODE" == "--repair" && "$(id -u)" -ne 0 ]]' in r
    assert "runuser -u harrypotter -- test -r" in r
    assert "install -d -o harrypotter -g harrypotter -m 0700" in r
    assert 'flock -n 9' in r
    assert "systemctl is-active comfyui.service" in r
    assert "systemctl is-active ai-gateway.service" in r
    assert "dev-residency.blocked" in r
    assert 'gpu_reuse_safe")=="NOT_VERIFIED"' in r
    assert 'n1_gpu_grants")=="NOT_ADMITTED"' in r
    assert "AMD_VISIBLE_OWNER_IS_ORIGINAL_COMFYUI_ONLY" in r
    assert "if pids!=expected" in r
    assert "sha256" in r
    assert "real-comfy-gpu-result.json" in r
    assert "mkdir -m 0700" in r
    assert r.index("FAILED_DEV_GPU_TEST_EVIDENCE_ARCHIVED_SHA256_PASS") < r.index(
        'mv "$BASE/dev-residency.blocked"')
    for forbidden in ("systemctl restart ","systemctl stop ","systemctl start ",
                      "systemctl disable ", "systemctl enable ",
                      "update-grub","rmmod","setpci","nvidia-smi -pl",
                      "rm -rf","sudo -n"):
        assert forbidden not in r
    assert "--check" in r and "--repair" in r


def test_gpu_harness_refuses_root_owned_workdirs_without_autocreating():
    s=read("real_comfy_gpu_rm_harness.py")
    assert 'for folder in ("input","output","temp","user"):' in s
    assert "path.is_symlink() or not path.is_dir()" in s
    assert "metadata.st_uid!=1000" in s
    assert "metadata.st_gid!=1000" in s
    assert "stat.S_IMODE(metadata.st_mode)!=0o700" in s
    assert "raise RuntimeError" in s
    assert '(BASE/folder).mkdir(parents=True,exist_ok=True)' not in s
    assert "DevicePolicy=closed" in s
    assert "gateway_comfy_ondemand_dev_mode=True" in s
    assert "RECOVERY_SAFE=PASS" not in s
    assert 'GPU_REUSE_SAFE=PASS' not in s


def test_baseline_watchdog_and_no_implicit_prod_cutover():
    s=read("run-maintenance-dev.sh")
    w=read("rollback.sh")
    assert "systemd-run --system --on-active=12min" in s
    assert 'install -o root -g root -m 0700 "$ROLLBACK"' in s
    assert s.index("ROLLBACK_WATCHDOG_ARMED") < s.index("systemctl stop ai-gateway.service")
    assert w.index('systemctl stop "$DEV"') < w.index("systemctl start comfyui.service")
    assert w.index("systemctl start comfyui.service") < w.index("systemctl start ai-gateway.service")
    assert "ROLLBACK_BLOCKED_TEST_CGROUP_NONEMPTY" in w
    assert "ROLLBACK_BLOCKED_TEST_PORT_STILL_OPEN" in w
    assert "KillMode=control-group" in read("real_comfy_gpu_rm_harness.py")


def test_script_archive_matches_live_staging_if_present():
    live=Path("/srv/ai-data/staging/comfy-ondemand-maintenance-dev-20261023")
    if not live.exists():
        return
    for name in ("run-maintenance-dev.sh","recover-after-failure-dev.sh",
                 "rollback.sh","real_comfy_gpu_rm_harness.py"):
        assert (live/name).read_bytes()==(D/name).read_bytes()
