"""One-shot AMD Radeon 890M DEV stop-refusal evidence and safety boundary."""
import hashlib
import json
from pathlib import Path
import subprocess

import pytest

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/"docs/reports/RM_COMFY_REAL_GPU_STOP_FAULT_DEV_2026-10-24.json"
REPORT=ROOT/"docs/reports/RM_COMFY_STOP_REFUSAL_REAL_GPU_DEV_2026-10-24_PL.md"
SCRIPTS=ROOT/"deploy/comfy-ondemand-dev/fault-stop-dev-20261024"


def result():
    return json.loads(DATA.read_text())


def test_real_gpu_then_deliberate_stop_failure_is_not_driver_reuse_approval():
    j=result()
    assert j["verdict"]=="DEV_REAL_AMD_VAE_STOP_REFUSAL_AND_PRODUCTION_ROLLBACK_PASS"
    assert j["production_cutover"]=="NOT_DEPLOYED"
    assert j["gpu_reuse_safe"]=="NOT_VERIFIED"
    assert j["n1_shared_gpu_grant"]=="NOT_ADMITTED"
    assert "simulated controller stop refusal" in j["scope"]
    assert "GPU_REUSE_SAFE/E_safe still NOT_VERIFIED" in j["verification_limits"]


def test_png_systemd_rollback_and_live_postflight_are_source_attested():
    r=result()["outcome"]
    assert "AMD Radeon 890M" in r["genuine_gpu_backend"]
    assert r["VAE_decode_seconds"]>0
    assert r["output_png"]["dimensions_px"]==[64,64]
    assert r["output_png"]["bytes"]>1000
    assert len(r["output_png"]["sha256"])==64
    assert r["dev_failure_marker_retained"] is True
    assert r["dev_negative_result_file_retained"] is True
    assert r["dev_unit_stopped_by_bounded_rollback"] is True
    assert r["watchdog_unloaded"] is True
    assert r["test_port_closed"] is True
    assert r["production_gateway_comfyui_ollama_restored"] is True
    assert r["production_gateway_health"]=="ok"
    assert r["production_comfyui_queue_and_models_empty"] is True
    assert r["production_rm_recovery_required"] is False
    assert r["nvidia_postflight"]["pstate"]=="P8"
    assert r["nvidia_postflight"]["link"]=="Gen3x4"
    assert r["nvidia_postflight"]["memory_mib"]<=256
    for data in r["pcie_aer_totals"].values():
        assert all(x==0 for x in data.values())


def test_machine_record_does_not_misrepresent_original_log_access():
    s=DATA.read_text()
    assert "Original root-owned failed harness record and stop injection trace not directly read" in s
    assert "raw_logs" in s
    assert "PRODUCTION_CUTOVER=PASS" not in s
    assert "NOT_DEPLOYED" in s
    assert "NOT_VERIFIED" in REPORT.read_text()
    assert "PHYSICAL GPU CRASH/OOM NOT TESTED" in REPORT.read_text()


def test_original_gpu_image_hash_on_host_when_present():
    folder=Path("/srv/ai-data/staging/comfy-ondemand-faults-dev-20261024")
    image=folder/"output/rm-comfy-dev-flux2-vae_00001_.png"
    if not image.is_file():
        pytest.skip("original GPU test PNG only stored on the physical host")
    blob=image.read_bytes()
    expected=result()["outcome"]["output_png"]
    assert blob[:8]==b"\x89PNG\r\n\x1a\n"
    assert int.from_bytes(blob[16:20],"big")==64
    assert int.from_bytes(blob[20:24],"big")==64
    assert len(blob)==expected["bytes"]
    assert hashlib.sha256(blob).hexdigest()==expected["sha256"]
    marker=folder/"dev-residency.blocked"
    if marker.is_file():
        # Earlier state: unresolved negative DEV test, no retry allowed.
        assert (folder/"real-comfy-gpu-result.json").is_file()
    else:
        # Later state: the operator explicitly reviewed/archived this
        # particular fail-closed result. It is incorrect to demand that the
        # active marker remain AFTER a verified archive transition.
        archive_record=ROOT/"docs/reports/RM_COMFY_STOP_FAULT_ARCHIVE_ACCEPTED_2026-10-24.json"
        archived=json.loads(archive_record.read_text())
        assert archived["verdict"]=="DEV_STOP_FAULT_ARCHIVED_AND_ACTIVE_RECOVERY_FENCE_CLEARED"
        assert archived["independent_active_marker_absent"] is True
        assert archived["independent_active_negative_result_absent"] is True
        assert archived["independent_archive_metadata"]["mode"]=="0700"
        assert archived["independent_archive_metadata"]["interior_access"]=="UNVERIFIED_FROM_NONROOT"
        archive_dir=folder/"accepted-stop-fault-20261024-0752"
        assert archive_dir.is_dir()
        assert archive_dir.stat().st_uid==0
        assert not (folder/"real-comfy-gpu-result.json").exists()


def test_scoped_archive_script_never_automatically_clears_marker():
    p=SCRIPTS/"review-and-archive-stop-fault-dev.sh"
    source=p.read_text()
    assert "MODE=--check" in source
    assert 'if [[ "$MODE" == "--archive" && "$(id -u)" -ne 0 ]]' in source
    assert "EXACT_INJECTED_RM_STOP_FAILURE_RECOGNIZED_PASS" in source
    assert "NEGATIVE_GPU_FAULT_EVIDENCE_COPIED_SHA256_PASS" in source
    assert "ONLY_RESTORED_COMFY_OWNS_AMD_GPU_PASS" in source
    assert "DEV_STOP_FAULT_ARCHIVED_AND_RECOVERY_FENCE_CLEARED_FOR_FUTURE_TEST_PASS" in source
    assert source.index("NEGATIVE_GPU_FAULT_EVIDENCE_COPIED_SHA256_PASS") < source.index(
        'mv "$BASE/dev-residency.blocked"')
    assert 'flock -n 9' in source
    for bad in ("systemctl start ", "systemctl stop ", "systemctl restart ",
                "setpci", "rmmod", "modprobe", "nvidia-smi -pl"):
        assert bad not in source
    v=subprocess.run(["bash","-n",str(p)],capture_output=True,text=True,timeout=4)
    assert v.returncode==0,v.stderr


def test_live_archive_source_matches_released_dev_code():
    path=Path("/srv/ai-data/staging/comfy-ondemand-faults-dev-20261024/review-and-archive-stop-fault-dev.sh")
    if not path.exists():
        pytest.skip("host-only DEV recovery script")
    assert path.read_bytes()==(SCRIPTS/"review-and-archive-stop-fault-dev.sh").read_bytes()
